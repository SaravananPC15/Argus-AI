"""
log_digest.py — Protocol Smart Log Digest (Daily Performance Summary).

End-of-day rollup: pulls today's git commits, today's executed actions
(from audit.py), and how much the nexus graph grew today, and asks the
LLM to compress it into a punchy 2-line conversational Tanglish summary
suitable for TTS playback. This is the natural "so what did you actually
do today" companion to the raw audit log.
"""

import time
import datetime
import git
import ollama
import model_router
import audit
import nexus_graph


def _todays_commits():
    try:
        repo = git.Repo(".", search_parent_directories=True)
        since = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
        commits = list(repo.iter_commits(since=since.isoformat()))
        return [c.message.strip().split("\n")[0] for c in commits]
    except Exception:
        return []


def _todays_actions():
    start_of_day = time.mktime(datetime.date.today().timetuple())
    actions = audit.get_recent_actions(limit=200)
    return [a for a in actions if a["timestamp"] >= start_of_day]


def generate_digest() -> str:
    """Entry point for executor.py's 'log_digest' action, and also what
    a scheduled end-of-day Chronos task would call."""
    commits = _todays_commits()
    actions = _todays_actions()
    graph_nodes_today = nexus_graph.node_count()  # cumulative; still useful context

    if not commits and not actions:
        return "Quiet day, macha — no commits or actions logged today."

    action_summary = ", ".join(f"{a['action']}({a['target'][:30]})" for a in actions[:15])
    commit_summary = "; ".join(commits[:10])

    prompt = f"""
    Summarize today's work into a punchy 2-line conversational Tanglish
    (Tamil + English mix) status report, like you're catching up a friend.
    Mention the roughly {len(actions)} actions and {len(commits)} commits if relevant.
    Be specific where possible, not generic. No markdown, no bullet points, just 2 spoken lines.

    TODAY'S GIT COMMITS: {commit_summary if commit_summary else "none"}
    TODAY'S ACTIONS: {action_summary if action_summary else "none"}
    PROJECT GRAPH SIZE: {graph_nodes_today} total nodes tracked
    """
    try:
        response = ollama.chat(
            model=model_router.select_model("smart_log_digest"),
            messages=[{'role': 'system', 'content': prompt}]
        )
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[Log Digest Error]: {e}")
        return f"Today: {len(commits)} commits, {len(actions)} actions logged. Full breakdown's in the audit log."
