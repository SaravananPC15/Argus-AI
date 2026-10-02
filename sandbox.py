"""
sandbox.py — Protocol Shadow Sandbox Execution.

Runs a piece of Python (or an arbitrary command) somewhere other than
directly in Argus's own process, so a bug in generated code -- an
infinite loop, a runaway memory allocation, an accidental `rm -rf` -- 
doesn't take the whole assistant down or touch the real filesystem.

HONEST SCOPING, READ BEFORE TREATING THIS AS A SECURITY BOUNDARY:

Docker (used automatically when the `docker` CLI is installed AND its
daemon is actually reachable) is real OS-level isolation -- its own
filesystem, `--network none`, memory/CPU/pids limits, `--read-only`.

The FALLBACK -- used automatically whenever Docker isn't available --
is a restricted subprocess: its own scratch temp directory, a hard
timeout, and (on Linux/macOS, via the stdlib `resource` module) CPU
time and address-space limits. That is meaningfully safer than running
generated code directly inside Argus's own process, but it is NOT a
security boundary against genuinely adversarial code: a subprocess
still shares the same OS kernel, user account, and filesystem
permissions as everything else Argus runs, and `resource` limits don't
exist at all on Windows (the timeout still applies there; the
memory/CPU caps silently don't). Use this to catch accidental bugs in
code you wrote or reviewed -- not to safely execute code you don't
trust from a source you don't control.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MEMORY_LIMIT_MB = 512
_WEAK_BACKEND_LABEL = "subprocess (weaker isolation -- see sandbox.py's module docstring)"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
        return result.returncode == 0
    except Exception:
        return False


def run_in_docker(code: str, timeout: int = DEFAULT_TIMEOUT_SECONDS,
                   memory_mb: int = DEFAULT_MEMORY_LIMIT_MB, image: str = "python:3.11-slim") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        script_path = os.path.join(tmp, "script.py")
        with open(script_path, "w") as f:
            f.write(code)
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            f"--memory={memory_mb}m",
            "--cpus=1",
            "--pids-limit=64",
            "--read-only",
            "-v", f"{script_path}:/sandbox/script.py:ro",
            "-w", "/sandbox",
            image, "python", "script.py",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {"backend": "docker", "returncode": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr, "timed_out": False}
        except subprocess.TimeoutExpired:
            return {"backend": "docker", "returncode": None, "stdout": "",
                    "stderr": f"Killed after exceeding {timeout}s timeout.", "timed_out": True}


def _limited_preexec(memory_mb: int, cpu_seconds: int):
    def set_limits():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            mem_bytes = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except Exception:
            pass  # not available on this platform (e.g. Windows) -- the outer timeout still applies
    return set_limits


def run_in_subprocess(code: str, timeout: int = DEFAULT_TIMEOUT_SECONDS,
                       memory_mb: int = DEFAULT_MEMORY_LIMIT_MB) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        script_path = os.path.join(tmp, "script.py")
        with open(script_path, "w") as f:
            f.write(code)

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        kwargs = {}
        if platform.system() != "Windows":
            kwargs["preexec_fn"] = _limited_preexec(memory_mb, timeout)

        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True, timeout=timeout,
                cwd=tmp, env=env, **kwargs,
            )
            return {"backend": _WEAK_BACKEND_LABEL, "returncode": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr, "timed_out": False}
        except subprocess.TimeoutExpired:
            return {"backend": _WEAK_BACKEND_LABEL, "returncode": None, "stdout": "",
                    "stderr": f"Killed after exceeding {timeout}s timeout.", "timed_out": True}


def run_sandboxed(code: str, timeout: int = DEFAULT_TIMEOUT_SECONDS,
                   memory_mb: int = DEFAULT_MEMORY_LIMIT_MB, prefer_docker: bool = True) -> dict:
    """The entry point executor.py's 'run_script' handler now calls
    instead of subprocess.run() directly. Picks Docker automatically
    when it's actually usable (installed AND daemon reachable, checked
    fresh each call since that can change between runs), otherwise the
    weaker-but-still-better-than-nothing subprocess fallback."""
    if prefer_docker and _docker_available():
        return run_in_docker(code, timeout, memory_mb)
    return run_in_subprocess(code, timeout, memory_mb)


if __name__ == "__main__":
    print("Docker available:", _docker_available())

    print("\n--- normal script ---")
    r = run_sandboxed("print('hello from the sandbox')\nprint(2 + 2)")
    print(r)

    print("\n--- infinite loop (should be killed at the timeout) ---")
    r = run_sandboxed("while True:\n    pass", timeout=2)
    print({k: v for k, v in r.items() if k != "stdout"})

    print("\n--- runaway memory allocation (should be killed on Linux/macOS via RLIMIT_AS) ---")
    r = run_sandboxed(
        "x = bytearray(2 * 1024 * 1024 * 1024)  # try to grab 2GB\nprint('should not get here')",
        timeout=10, memory_mb=128,
    )
    print({k: v for k, v in r.items() if k != "stdout"})

    print("\n--- confirms scratch-dir isolation: script cannot see this project's files ---")
    r = run_sandboxed("import os\nprint(sorted(os.listdir('.')))")
    print(r["stdout"])
