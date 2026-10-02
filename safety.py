"""
safety.py — Feature 4: Confirmation gate for risky/destructive actions.

Several actions Argus can take are hard or impossible to undo: pushing to
git, locking/rebooting the machine, running an arbitrary script, or
emptying the recycle bin. Previously these fired immediately the moment
the LLM classified an intent that way. This module centralizes the
"is this risky?" check so every entry point (voice loop, wake word,
dashboard, remote server) can gate on it consistently.
"""

# Actions that are always considered risky, regardless of target.
_ALWAYS_RISKY_ACTIONS = {"git_push", "run_script"}

# For system_command, only some targets are actually destructive/risky —
# volume/mute/status checks are harmless and shouldn't require confirmation.
_RISKY_SYSTEM_COMMAND_KEYWORDS = ["lock", "secure", "shutdown", "restart", "reboot"]

# hands.py's own action names (legacy path) that are risky.
_RISKY_HANDS_ACTIONS = {"empty_recycle_bin"}


def is_risky(action: str, target: str = "") -> bool:
    """Returns True if this action should be confirmed with the user
    before it actually runs. Respects the "risk_confirmation" toggle in
    the control-center UI — if the user has turned that off, actions run
    without a confirmation step (their own informed choice on their own
    machine, same as disabling "confirm before delete" in any app)."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("risk_confirmation"):
            return False
    except Exception:
        pass

    if action in _ALWAYS_RISKY_ACTIONS or action in _RISKY_HANDS_ACTIONS:
        return True
    if action == "system_command":
        target_lower = (target or "").lower()
        return any(kw in target_lower for kw in _RISKY_SYSTEM_COMMAND_KEYWORDS)
    return False


def confirmation_prompt(action: str, target: str = "") -> str:
    """A short, spoken/displayed prompt asking the user to confirm."""
    if action == "git_push":
        return "That will commit and push your code to the remote repository. Say 'confirm' to proceed, or anything else to cancel."
    if action == "run_script":
        return f"That will execute the script '{target}' on your machine. Say 'confirm' to proceed, or anything else to cancel."
    if action == "empty_recycle_bin":
        return "That will permanently empty the recycle bin. Say 'confirm' to proceed, or anything else to cancel."
    if action == "system_command":
        return f"That will run a system-level command ({target}). Say 'confirm' to proceed, or anything else to cancel."
    return "That action can't be undone. Say 'confirm' to proceed, or anything else to cancel."


def is_confirmation(user_text: str) -> bool:
    """Loose match for a user's affirmative confirmation reply."""
    if not user_text:
        return False
    text = user_text.strip().lower()
    return text in {"confirm", "yes", "confirmed", "yes confirm", "do it", "go ahead", "proceed"}
