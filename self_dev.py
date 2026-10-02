"""
self_dev.py -- Self-Development Engine ("self-healing and self-regenerative").

What this actually does, precisely:

1. DIAGNOSIS: periodically re-runs the exact static checks used to audit
   this codebase in the first place -- py_compile syntax validation and
   cross-module import resolution -- against the live project directory.
   This catches things like a bad manual edit breaking an import, or a
   partially-written file.

2. PATCH DRAFTING: for each issue found, asks the LLM to draft a full
   corrected version of the broken file, computes a unified diff against
   the original for human review, and writes both to self_patches/ with
   an entry in self_dev_log.json (status: "pending").

3. FEATURE-GAP DETECTION: scans audit.py's action log for repeated
   requests Argus couldn't handle (the "isn't fully mapped" fallback),
   and when a pattern repeats, drafts a short written proposal for a new
   action to cover it -- again logged as "pending", not wired in.

4. HUMAN APPROVAL GATE: nothing above ever touches the live source files
   or restarts anything on its own. approve_patch() is the only function
   that writes to the real file, and it's meant to be called from a
   human clicking "Approve" in the control-center UI (or a CLI command).
   This mirrors how Dependabot/Renovate work -- they open a PR, they don't
   merge to main -- which is the right pattern for any code that can edit
   itself, not just this project. Given this codebase can already run
   shell commands, push to git, and (with other protocols enabled) lock
   your workstation or gate physical access, letting it silently rewrite
   its own logic with no review step is a bad idea regardless of how
   convenient "fully autonomous" sounds.

Every proposal -- approved, rejected, or still pending -- stays in
self_dev_log.json permanently, which is what the UI's "Log History"
panel reads.
"""

import ast
import glob
import os
import json
import time
import difflib
import shutil
import ollama
import model_router
import audit

PATCH_DIR = "self_patches"
LOG_FILE = "self_dev_log.json"


# ---------------------------------------------------------------------
# Dev log (this is what the "Log History" button in the UI reads)
# ---------------------------------------------------------------------

def _load_log():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def _append_log_entry(entry: dict) -> str:
    log = _load_log()
    entry["id"] = f"patch_{int(time.time() * 1000)}_{len(log)}"
    entry["created_at"] = time.time()
    entry["status"] = entry.get("status", "pending")
    log.append(entry)
    _save_log(log)
    return entry["id"]


def get_log(limit: int = 100):
    """Newest first -- what the UI's Log History panel displays."""
    return list(reversed(_load_log()))[:limit]


# ---------------------------------------------------------------------
# 1. Diagnosis -- same checks used to audit this codebase originally
# ---------------------------------------------------------------------

def run_diagnosis():
    """Returns a list of {"file", "type", "detail"} issues found in the
    live .py files. type is 'syntax_error' or 'broken_import'."""
    issues = []
    files = glob.glob("*.py")
    mod_names = {os.path.splitext(f)[0] for f in files}
    defs = {}

    for f in files:
        mod = os.path.splitext(f)[0]
        try:
            src = open(f, encoding="utf-8").read()
            tree = ast.parse(src, filename=f)
        except SyntaxError as e:
            issues.append({"file": f, "type": "syntax_error", "detail": f"Line {e.lineno}: {e.msg}"})
            continue
        except OSError:
            continue

        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
                    elif isinstance(t, ast.Tuple):
                        names.update(e.id for e in t.elts if isinstance(e, ast.Name))
            elif isinstance(node, ast.ImportFrom):
                names.update((a.asname or a.name) for a in node.names)
            elif isinstance(node, ast.Import):
                names.update((a.asname or a.name).split(".")[0] for a in node.names)
        defs[mod] = names

    for f in files:
        try:
            src = open(f, encoding="utf-8").read()
            tree = ast.parse(src, filename=f)
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in mod_names:
                target = defs.get(node.module, set())
                for alias in node.names:
                    if alias.name != "*" and alias.name not in target:
                        issues.append({
                            "file": f, "type": "broken_import",
                            "detail": f"imports '{alias.name}' from '{node.module}.py' but it's not defined there"
                        })
    return issues


# ---------------------------------------------------------------------
# 2. Patch drafting -- proposes, never applies
# ---------------------------------------------------------------------

def _draft_fix(filepath: str, issue_detail: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        original_source = f.read()

    prompt = f"""
    This Python file has a bug: {issue_detail}

    Output ONLY the complete corrected file content, nothing else -- no
    markdown fences, no explanation, just the raw fixed Python source,
    preserving everything else about the file exactly as-is.

    FILE ({filepath}):
    {original_source}
    """
    response = ollama.chat(model=model_router.select_model("", complexity_hint="heavy"),
                            messages=[{'role': 'system', 'content': prompt}])
    fixed_source = response['message']['content'].strip()
    if fixed_source.startswith("```"):
        fixed_source = "\n".join(fixed_source.split("\n")[1:])
    if fixed_source.endswith("```"):
        fixed_source = "\n".join(fixed_source.split("\n")[:-1])
    return original_source, fixed_source


def propose_patches_for_diagnosis():
    """Runs diagnosis, and for every NEW issue (not already pending/logged
    for this file+detail), drafts a proposed fix. Returns the list of
    newly created proposal IDs. Never touches the live files."""
    issues = run_diagnosis()
    existing = _load_log()
    already_seen = {(e["file"], e["detail"]) for e in existing if e.get("type") in ("syntax_error", "broken_import")}

    os.makedirs(PATCH_DIR, exist_ok=True)
    new_ids = []

    for issue in issues:
        key = (issue["file"], issue["detail"])
        if key in already_seen:
            continue
        try:
            original, fixed = _draft_fix(issue["file"], issue["detail"])
        except Exception as e:
            print(f"[Self-Dev] Failed to draft fix for {issue['file']}: {e}")
            continue

        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True), fixed.splitlines(keepends=True),
            fromfile=f"{issue['file']} (current)", tofile=f"{issue['file']} (proposed)"
        ))

        patch_path = os.path.join(PATCH_DIR, f"{issue['file']}.{int(time.time())}.proposed")
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(fixed)

        entry_id = _append_log_entry({
            "kind": "patch",
            "type": issue["type"],
            "file": issue["file"],
            "detail": issue["detail"],
            "patch_path": patch_path,
            "diff_preview": "".join(diff_lines[:40]),
            "summary": f"Self-diagnosed {issue['type'].replace('_', ' ')} in {issue['file']}: {issue['detail']}",
        })
        new_ids.append(entry_id)
        print(f"[Self-Dev] Drafted a proposed fix for {issue['file']} ({entry_id}). Awaiting your approval.")

    return new_ids


# ---------------------------------------------------------------------
# 3. Feature-gap detection -- proposes ideas, never wires them in
# ---------------------------------------------------------------------

def detect_feature_gaps(min_repeats: int = 3):
    """Looks for repeated 'I received the command, but the local execution
    path isn't fully mapped' results in the audit log -- a sign the user
    keeps asking for something Argus doesn't know how to do -- and drafts
    a short written proposal (not code) for what a new action could look
    like. Logged the same way as patches, for the same approval flow."""
    actions = audit.get_recent_actions(limit=300)
    unmapped = [a for a in actions if "isn't fully mapped" in (a.get("result") or "")]

    if len(unmapped) < min_repeats:
        return []

    existing = _load_log()
    already_proposed_targets = {e.get("target_sample") for e in existing if e.get("kind") == "feature_gap"}

    targets_sample = "; ".join(a["target"] for a in unmapped[:10])
    if targets_sample in already_proposed_targets:
        return []

    prompt = f"""
    A user's assistant keeps getting requests it can't handle. Here are
    recent examples of what it couldn't do: {targets_sample}

    In 2-3 sentences, propose ONE new capability/action this assistant
    could add to cover these, including roughly what it would need to do
    technically. Be concrete and specific, not generic advice.
    """
    try:
        response = ollama.chat(model=model_router.select_model("", complexity_hint="heavy"),
                                messages=[{'role': 'system', 'content': prompt}])
        proposal_text = response['message']['content'].strip()
    except Exception as e:
        print(f"[Self-Dev] Feature-gap proposal failed: {e}")
        return []

    entry_id = _append_log_entry({
        "kind": "feature_gap",
        "target_sample": targets_sample,
        "occurrences": len(unmapped),
        "summary": f"Noticed {len(unmapped)} requests I couldn't handle. Idea: {proposal_text}",
        "status": "proposed",
    })
    print(f"[Self-Dev] Logged a new feature-gap proposal ({entry_id}).")
    return [entry_id]


# ---------------------------------------------------------------------
# 4. Human approval gate -- the ONLY functions that touch live files
# ---------------------------------------------------------------------

def approve_patch(patch_id: str) -> str:
    log = _load_log()
    entry = next((e for e in log if e["id"] == patch_id), None)
    if not entry or entry.get("kind") != "patch":
        return "No such pending patch."
    if entry["status"] != "pending":
        return f"Patch is already {entry['status']}."

    backup_path = entry["file"] + f".backup.{int(time.time())}"
    shutil.copy(entry["file"], backup_path)
    shutil.copy(entry["patch_path"], entry["file"])

    entry["status"] = "approved"
    entry["approved_at"] = time.time()
    entry["backup_path"] = backup_path
    _save_log(log)

    os.makedirs("audio_cache", exist_ok=True)
    with open("audio_cache/self_dev_restart_signal.txt", "w") as f:
        f.write(entry["file"])

    return f"Applied. Backed up the original to {backup_path} first."


def reject_patch(patch_id: str) -> str:
    log = _load_log()
    entry = next((e for e in log if e["id"] == patch_id), None)
    if not entry:
        return "No such proposal."
    entry["status"] = "rejected"
    entry["rejected_at"] = time.time()
    _save_log(log)
    return "Rejected. Left your original file untouched."


def get_pending_patches():
    return [e for e in _load_log() if e.get("kind") == "patch" and e.get("status") == "pending"]


# ---------------------------------------------------------------------
# Background cycle
# ---------------------------------------------------------------------

def run_cycle():
    """One diagnosis + feature-gap pass. Call this on an interval (e.g.
    from launch.py or a scheduled task) -- it's cheap when there's nothing
    new to find."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("self_dev_engine"):
            return
    except Exception:
        pass

    propose_patches_for_diagnosis()
    detect_feature_gaps()
