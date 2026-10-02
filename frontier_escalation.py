"""
frontier_escalation.py — Protocol Frontier Escalation.

The honest answer to "make Argus know everything without training":
that's not a real category of technology, on any hardware, built by
anyone (see the conversation this came out of). What IS real: a model
doesn't need to have memorized an answer if it can either look it up
(MCP Bridge, document_processor's RAG) or, for the rare question that's
genuinely beyond what a 1B/8B local model reasons well about, hand off
to a real frontier model on purpose.

THIS IS THE ONLY PLACE IN ARGUS WHERE A QUERY LEAVES THE LOCAL NETWORK
AS PART OF NORMAL REASONING. Not MCP Bridge (that's you configuring a
specific LOCAL stdio tool server), not graph_sync (LAN-only), not
acoustic_link (audio, not network). This one actually calls Anthropic's
API over the internet, and that's a real, deliberate exception to
everything else this project does -- which is exactly why it never
fires without explicit confirmation, regardless of which action or
trigger phrase got here. See escalate() below: confirmed=False (the
default) ALWAYS returns a confirmation prompt and sends nothing. Even
if brain.py's small routing model misclassifies an ordinary question
into this action -- it's a 1B model, it will sometimes be wrong -- the
worst case is an unwanted confirmation prompt, never an unwanted
network request. The gate is structural, not just a matter of prompt
wording being careful enough.

Off by default, like every other protocol that adds new connectivity.
Needs your own ANTHROPIC_API_KEY (same env var the official SDK looks
for already -- nothing Argus-specific to remember) and a real API
billing relationship -- unlike everything else here, this has an
actual per-use cost, and recent_escalations() below exists specifically
so "is this quietly costing me money" has a real answer, not a guess.

HONEST LIMITATION: the `anthropic` package isn't installed in the
environment this was built in, and there's no network there to install
it or a real API key to call with -- so unlike most of this project,
the actual API call in escalate() could not be run end-to-end before
delivery. Written carefully against Anthropic's documented, stable
messages API. What COULD be tested, and was: the confirmation gate
logic, the toggle check, and error handling for a missing API key --
see _self_test().
"""

import os
import time

DEFAULT_MODEL = "claude-sonnet-5"  # check Anthropic's current model list if this has moved on by the time you read it
MAX_TOKENS = 2048

_recent = []  # in-memory only: [{"time", "query_preview", "model"}, ...] -- not persisted, resets when Argus restarts


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=api_key)


def escalate(query: str, confirmed: bool = False, model: str = DEFAULT_MODEL) -> dict:
    """
    confirmed=False (always the first call): returns needs_confirmation,
    sends nothing. confirmed=True: actually calls the API. Callers
    should never skip straight to confirmed=True on a first attempt --
    see executor.py's frontier_escalate handler for how the "confirmed"
    re-entry is meant to work (same pattern as mcp_bridge.py's risky
    tool-call confirmation).
    """
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("frontier_escalation"):
            return {"ok": False, "error": "Protocol Frontier Escalation is toggled off."}
    except Exception:
        return {"ok": False, "error": "Couldn't check the feature toggle -- refusing rather than assuming it's on."}

    if not confirmed:
        return {
            "ok": False,
            "needs_confirmation": True,
            "message": (f'This sends "{query}" to Anthropic\'s API ({model}) -- leaving your local '
                        f'network, which nothing else Argus does by default. Say it again with the '
                        f'word "confirmed" to actually send it.'),
        }

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "error": "ANTHROPIC_API_KEY isn't set in this environment -- see SETUP.md."}

    client = _client()
    if client is None:
        return {"ok": False, "error": "The `anthropic` package isn't installed -- run: pip install anthropic"}

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": query}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
    except Exception as e:
        return {"ok": False, "error": f"API call failed: {e}"}

    _recent.append({"time": time.time(), "query_preview": query[:80], "model": model})
    return {"ok": True, "response": text, "model": model}


def recent_escalations(limit: int = 20) -> list:
    """What's actually left the local network recently, most recent
    first -- exists so this has a real, checkable answer instead of
    trusting that the confirmation step was the only safeguard anyone
    ever relies on."""
    return list(reversed(_recent[-limit:]))


def _self_test():
    import unittest.mock as mock

    # 1. Toggle off -> refuses before even checking confirmation, no API touched.
    fake_ft_off = mock.MagicMock()
    fake_ft_off.is_enabled.return_value = False
    import sys
    sys.modules["feature_toggles"] = fake_ft_off
    result = escalate("what's the capital of France", confirmed=True)
    assert result["ok"] is False and "toggled off" in result["error"]
    print("[1/4] Toggle off refuses outright, even with confirmed=True: OK")

    # 2. Toggle on, not yet confirmed -> confirmation prompt, nothing sent,
    #    _recent stays empty.
    fake_ft_on = mock.MagicMock()
    fake_ft_on.is_enabled.return_value = True
    sys.modules["feature_toggles"] = fake_ft_on
    _recent.clear()
    result = escalate("explain quantum entanglement simply", confirmed=False)
    assert result["needs_confirmation"] is True
    assert len(_recent) == 0
    print("[2/4] Unconfirmed request returns a confirmation prompt and sends nothing: OK")

    # 3. Confirmed, but no API key set -> clean error, not a crash, nothing logged.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    result = escalate("explain quantum entanglement simply", confirmed=True)
    assert result["ok"] is False and "ANTHROPIC_API_KEY" in result["error"]
    assert len(_recent) == 0
    print("[3/4] Confirmed but no API key -> clean error, nothing logged as sent: OK")

    # 4. Confirmed + a (fake) working client -> actually calls, logs it,
    #    recent_escalations() reflects it.
    fake_block = mock.MagicMock()
    fake_block.text = "Entanglement, briefly: two particles' states stay correlated no matter the distance."
    fake_response = mock.MagicMock()
    fake_response.content = [fake_block]
    fake_client = mock.MagicMock()
    fake_client.messages.create.return_value = fake_response

    real_import = __import__
    with mock.patch("builtins.__import__", side_effect=lambda name, *a, **k: (
        mock.MagicMock(Anthropic=lambda api_key: fake_client) if name == "anthropic"
        else real_import(name, *a, **k)
    )):
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-testing"
        result = escalate("explain quantum entanglement simply", confirmed=True)

    assert result["ok"] is True and "correlated" in result["response"]
    assert len(_recent) == 1 and _recent[0]["model"] == DEFAULT_MODEL
    recent = recent_escalations()
    assert len(recent) == 1 and "quantum entanglement" in recent[0]["query_preview"]
    print("[4/4] Confirmed + working client -> real call made, logged, recent_escalations() reflects it: OK")

    del os.environ["ANTHROPIC_API_KEY"]
    print("\nAll frontier_escalation self-tests passed (confirmation gate, toggle check, error handling, "
          "and logging -- NOT the real Anthropic API call itself; see module docstring's honest limitation).")


if __name__ == "__main__":
    _self_test()
