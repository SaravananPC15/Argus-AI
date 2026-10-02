"""
mcp_bridge.py — Protocol MCP Tool Bridge.

Lets Argus use tools exposed by Model Context Protocol servers --
filesystem, git, databases, whatever you configure -- instead of
hand-writing a bespoke integration module for every new external
capability, the way castellan.py/scraping_vanguard.py/etc. each are.

PRIVACY IS THE DESIGN, NOT AN AFTERTHOUGHT. This makes Argus an MCP
*client* only -- it reaches OUT to tool servers Argus itself starts as
local subprocesses. It does NOT make Argus an MCP *server*. Nothing
about this lets another device, app, or person connect INTO Argus.
Three concrete choices enforce that, and none of them are the default
you'd get from just following the MCP quickstart docs:

  1. STDIO TRANSPORT ONLY. MCP supports both local servers (stdio: a
     subprocess talking over stdin/stdout pipes -- no network socket
     involved at all) and remote servers (HTTP/SSE: a real network
     endpoint, potentially on someone else's infrastructure). This
     file implements ONLY stdio, on purpose. Every server this
     connects to is a process running on YOUR machine, under YOUR
     account, with no port open for anything else to find.
  2. EMPTY BY DEFAULT. mcp_servers.json starts as an empty list. Zero
     servers are pre-configured. Nothing connects to anything until
     you explicitly add it by name yourself (add_server() below).
  3. CREDENTIALS NEVER TOUCH A TRACKED FILE. A server that needs an
     API token (GitHub, Slack, whatever) reads it from an environment
     variable YOU set locally -- same pattern as this project's
     existing ARGUS_GRAPH_SYNC_PASSPHRASE. mcp_servers.json stores
     which env var NAME to read, never the secret value itself.

HONEST LIMITATION, READ THIS BEFORE TRUSTING IT WITH ANYTHING THAT
MATTERS: this was written against the official `mcp` Python SDK's
documented client API (ClientSession / stdio_client /
StdioServerParameters). That package isn't installed in the sandbox
this was built in, and there's no network access there to install it
or a live MCP server to connect to -- so unlike almost everything else
in this project, the actual protocol handshake inside
connect_and_list_tools()/call_tool() could NOT be run end-to-end
before delivery. What COULD be tested, and was (see _self_test at the
bottom): config load/save/validation, the risky-tool-name safety
check as a pure function, and the full dispatch/caching/confirmation
logic against a mocked mcp package standing in for a real server.
Run a real server through this once yourself (`pip install mcp`, add
the official filesystem server, try mcp_list_tools) before relying on
it for anything you'd mind getting wrong.
"""

import asyncio
import json
import os
import re
import time

CONFIG_FILE = "mcp_servers.json"
_CACHE_TTL_SECONDS = 300

# Keyword-based caution flag for tool names/descriptions that sound
# destructive. MCP tools are open-ended -- unlike Argus's own fixed
# VALID_ACTIONS list, a connected server could expose ANYTHING,
# including something like a "delete_repo" or "drop_table" tool. This
# doesn't replace actually reading what you're connecting to; it's a
# last-line trip-wire, not a substitute for judgment.
#
# Split on any non-alphanumeric separator rather than using a \b-based
# regex: \b treats underscore as a word character, so a naive
# r"\bdelete\b" silently fails to match "delete_repository" -- exactly
# the snake_case style MCP tool names actually use. Caught by this
# file's own self-test before it shipped.
_RISKY_WORDS = {"delete", "remove", "drop", "destroy", "force", "purge", "wipe",
                 "truncate", "kill", "terminate", "revoke", "disable"}
_WORD_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")

_tool_cache = {"tools": {}, "fetched_at": 0.0}


def load_servers(path: str = CONFIG_FILE) -> list:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save_servers(servers: list, path: str = CONFIG_FILE):
    with open(path, "w") as f:
        json.dump(servers, f, indent=2)


def add_server(name: str, command: str, args: list = None, env_var_names: list = None,
               path: str = CONFIG_FILE) -> dict:
    """
    Registers a LOCAL (stdio) MCP server. `command`/`args` is exactly
    what gets subprocess-launched -- e.g. command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/home/you/documents"].
    `env_var_names` lists which environment variable NAMES (not
    values) this server reads credentials from, e.g. ["GITHUB_TOKEN"]
    -- documentation for you; the secret itself lives only in your
    shell environment, never in this file (see module docstring).
    """
    if not name or not name.strip():
        raise ValueError("Server name can't be empty.")
    servers = load_servers(path)
    if any(s["name"] == name for s in servers):
        raise ValueError(f"A server named '{name}' is already configured.")
    missing_env = [v for v in (env_var_names or []) if v not in os.environ]
    entry = {"name": name, "command": command, "args": args or [],
              "env_var_names": env_var_names or [], "enabled": True}
    servers.append(entry)
    save_servers(servers, path)
    if missing_env:
        print(f"[MCP Bridge] Warning: '{name}' expects env var(s) {missing_env}, "
              f"not currently set in this shell -- it'll likely fail to authenticate "
              f"until you set them.")
    return entry


def remove_server(name: str, path: str = CONFIG_FILE) -> bool:
    servers = load_servers(path)
    remaining = [s for s in servers if s["name"] != name]
    if len(remaining) == len(servers):
        return False
    save_servers(remaining, path)
    _tool_cache["tools"].pop(name, None)
    return True


def _get_server(name: str, path: str = CONFIG_FILE) -> dict:
    server = next((s for s in load_servers(path) if s["name"] == name), None)
    if server is None:
        raise ValueError(f"No configured MCP server named '{name}'. "
                          f"Configured: {[s['name'] for s in load_servers(path)]}")
    return server


def _is_risky(tool_name: str, description: str) -> bool:
    words = set(_WORD_SPLIT_RE.split(tool_name.lower())) | set(_WORD_SPLIT_RE.split((description or "").lower()))
    return bool(words & _RISKY_WORDS)


def _env_for(server_config: dict) -> dict:
    return {name: os.environ[name] for name in server_config.get("env_var_names", []) if name in os.environ}


async def connect_and_list_tools(server_config: dict) -> list:
    """Launches the server as a local subprocess (stdio), lists its
    advertised tools, then disconnects. UNTESTED LIVE -- see module
    docstring. Returns [{"name", "description", "input_schema"}]."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server_config["command"],
                                    args=server_config.get("args", []),
                                    env=_env_for(server_config))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [{"name": t.name, "description": t.description, "input_schema": t.inputSchema}
                    for t in result.tools]


async def call_tool(server_name: str, tool_name: str, arguments: dict,
                     confirmed: bool = False, path: str = CONFIG_FILE) -> dict:
    """Connects, invokes ONE tool, disconnects -- a short-lived
    connection per call rather than a persistent daemon, so nothing
    stays running/listening between calls. Refuses to run anything
    matching _RISKY_KEYWORDS unless confirmed=True. UNTESTED LIVE --
    see module docstring."""
    server_config = _get_server(server_name, path)
    tools = await connect_and_list_tools(server_config)
    matching = next((t for t in tools if t["name"] == tool_name), None)
    if matching is None:
        return {"ok": False, "error": f"'{server_name}' doesn't expose a tool called '{tool_name}'. "
                                        f"Available: {[t['name'] for t in tools]}"}

    if _is_risky(tool_name, matching["description"]) and not confirmed:
        return {"ok": False, "needs_confirmation": True,
                "message": f"'{tool_name}' sounds destructive ({matching['description'] or 'no description given'}). "
                           f"Confirm explicitly before I run it."}

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=server_config["command"],
                                    args=server_config.get("args", []),
                                    env=_env_for(server_config))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return {"ok": True, "result": [c.text if hasattr(c, "text") else str(c) for c in result.content]}


async def refresh_tool_cache(path: str = CONFIG_FILE) -> dict:
    """Actually launches every ENABLED configured server to discover
    its tools, and populates the cache get_prompt_snippet()/
    mcp_list_tools reads. This is the only function in this file that
    does real subprocess work on a schedule other than 'you explicitly
    called it' -- see get_prompt_snippet's docstring for why that
    split matters."""
    servers = [s for s in load_servers(path) if s.get("enabled", True)]
    all_tools = {}
    for server in servers:
        try:
            all_tools[server["name"]] = await connect_and_list_tools(server)
        except Exception as e:
            print(f"[MCP Bridge] Couldn't reach '{server['name']}': {e}")
            all_tools[server["name"]] = []
    _tool_cache["tools"] = all_tools
    _tool_cache["fetched_at"] = time.time()
    return all_tools


def get_prompt_snippet(path: str = CONFIG_FILE) -> str:
    """What brain.py calls on every routing decision -- CACHE-ONLY, no
    subprocess launches here, ever. A normal chat turn should never pay
    unpredictable latency for a feature it isn't using; that's the same
    reasoning context_compactor.py's no-op-when-under-budget path
    follows. Returns '' immediately if the bridge is off, nothing's
    configured, or the cache hasn't been populated yet (run the
    'mcp_list_tools' action, or call refresh_tool_cache() directly,
    after adding a server -- see SETUP.md)."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("mcp_bridge"):
            return ""
    except Exception:
        pass

    if not _tool_cache["tools"]:
        return ""

    lines = ["\nMCP TOOLS CURRENTLY AVAILABLE (Protocol MCP Tool Bridge):"]
    for server_name, tools in _tool_cache["tools"].items():
        for t in tools:
            lines.append(f"- {server_name}.{t['name']}: {t['description']}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def cache_age_seconds() -> float:
    if _tool_cache["fetched_at"] == 0.0:
        return float("inf")
    return time.time() - _tool_cache["fetched_at"]


if __name__ == "__main__":
    import tempfile
    import unittest.mock as mock

    tmp_path = os.path.join(tempfile.gettempdir(), "argus_test_mcp_servers.json")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # 1. Config CRUD + duplicate rejection -- no mcp package needed.
    add_server("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"], path=tmp_path)
    assert len(load_servers(tmp_path)) == 1
    try:
        add_server("filesystem", "npx", [], path=tmp_path)
        raise AssertionError("should have rejected a duplicate server name")
    except ValueError:
        pass
    print("[1/5] Config add/load + duplicate-name rejection: OK")

    # 2. Missing env var produces a warning but doesn't block saving
    #    (you might set the var a minute later -- refusing to save would
    #    be more annoying than useful).
    add_server("github", "npx", ["-y", "@modelcontextprotocol/server-github"],
               env_var_names=["GITHUB_TOKEN_DEFINITELY_NOT_SET"], path=tmp_path)
    assert len(load_servers(tmp_path)) == 2
    print("[2/5] Server needing an unset env var still saves (with a warning): OK")

    # 3. Remove works, and clears any cached tools for that server.
    _tool_cache["tools"]["filesystem"] = [{"name": "read_file", "description": "reads a file"}]
    assert remove_server("filesystem", path=tmp_path) is True
    assert remove_server("filesystem", path=tmp_path) is False  # already gone
    assert "filesystem" not in _tool_cache["tools"]
    print("[3/5] Remove server + cache cleared for it: OK")

    # 4. Risky-keyword detection -- pure function, no mock needed.
    assert _is_risky("delete_repository", "Permanently deletes a GitHub repo") is True
    assert _is_risky("read_file", "Reads the contents of a file") is False
    assert _is_risky("list_items", "") is False
    print("[4/5] Risky-tool-name keyword detection: OK")

    # 5. Full async dispatch against a MOCKED mcp package: normal tool
    #    call succeeds; a risky one is blocked without confirmation and
    #    proceeds once confirmed=True.
    class _FakeTool:
        def __init__(self, name, description):
            self.name, self.description, self.inputSchema = name, description, {}

    class _FakeListResult:
        def __init__(self, tools):
            self.tools = tools

    class _FakeContent:
        def __init__(self, text):
            self.text = text

    class _FakeCallResult:
        def __init__(self, content):
            self.content = content

    _FAKE_TOOLS = [_FakeTool("list_files", "Lists files in a directory"),
                   _FakeTool("delete_all", "Deletes everything in the directory, no confirmation")]

    class _FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            return _FakeListResult(_FAKE_TOOLS)

        async def call_tool(self, name, arguments):
            return _FakeCallResult([_FakeContent(f"ran {name} with {arguments}")])

    class _FakeStdioCM:
        def __init__(self, params):
            pass

        async def __aenter__(self):
            return ("r", "w")

        async def __aexit__(self, *a):
            return False

    fake_mcp = mock.MagicMock()
    fake_mcp.ClientSession = _FakeSession
    fake_mcp.StdioServerParameters = lambda command, args, env: {"command": command, "args": args, "env": env}
    fake_mcp_client_stdio = mock.MagicMock()
    fake_mcp_client_stdio.stdio_client = lambda params: _FakeStdioCM(params)

    import sys
    sys.modules["mcp"] = fake_mcp
    sys.modules["mcp.client"] = mock.MagicMock()
    sys.modules["mcp.client.stdio"] = fake_mcp_client_stdio

    add_server("testfs", "npx", ["-y", "fake-server"], path=tmp_path)

    async def _run_async_tests():
        safe = await call_tool("testfs", "list_files", {"path": "/tmp"}, path=tmp_path)
        assert safe["ok"] is True and "ran list_files" in safe["result"][0]

        blocked = await call_tool("testfs", "delete_all", {}, path=tmp_path)
        assert blocked["ok"] is False and blocked["needs_confirmation"] is True

        allowed = await call_tool("testfs", "delete_all", {}, confirmed=True, path=tmp_path)
        assert allowed["ok"] is True and "ran delete_all" in allowed["result"][0]

        cache = await refresh_tool_cache(path=tmp_path)
        assert "testfs" in cache and len(cache["testfs"]) == 2

    asyncio.run(_run_async_tests())
    print("[5/5] Full dispatch (mocked mcp package): safe call OK, risky call blocked, "
          "risky call proceeds once confirmed, cache refresh OK")

    os.remove(tmp_path)
    print("\nAll mcp_bridge self-tests passed (against a MOCKED mcp package -- see module "
          "docstring's honest limitation note before trusting this against a real server).")
