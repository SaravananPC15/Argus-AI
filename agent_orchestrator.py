import json
import asyncio
import os
import ollama
import model_router
from executor import run_local_command

CHECKPOINT_FILE = "audio_cache/workflow_checkpoint.json"


async def generate_execution_plan(objective):
    """Asks Llama 1B to break a complex goal down into a structured JSON list of commands."""

    # Protocol Round Table: for objectives that are genuinely multi-domain
    # (not most of them -- see round_table.py's complexity threshold),
    # convene the specialist roster FIRST and feed their synthesis in as
    # extra context. This is the "or get a complex task" auto-trigger;
    # the "assigned" trigger is the separate "round_table" action in
    # executor.py. A plain single-domain objective never comes close to
    # the threshold and this adds nothing to the prompt below.
    round_table_context = ""
    try:
        import round_table
        synthesis = round_table.maybe_auto_convene(objective)
        if synthesis:
            round_table_context = f"""
    A specialist round table already discussed this objective and reached this verdict --
    weigh it heavily when building the plan below:
    "{synthesis}"
    """
    except Exception as e:
        print(f"[Orchestrator] Round Table pre-check skipped: {e}")

    planner_prompt = f"""
    You are the Argus Task Planner Matrix. Your job is to break down a complex user objective into a series of discrete, sequential system steps.
    {round_table_context}
    You must output ONLY a valid JSON array of objects. Do not include markdown or conversational filler.
    Each object in the array must contain:
    1. "step_number": integer
    2. "action": Must be one of "open_app", "system_command", "vision_task", "casual_chat", or "ask_user"
    3. "target": The specific parameter for that action. For "ask_user", this is the exact clarifying question to ask.
    4. "description": A short human-readable note of what this step achieves.

    Use "ask_user" ONLY when the objective is genuinely ambiguous and you need information only the
    user can provide (e.g. which of two options, a missing filename, a missing time) before continuing.
    Do not overuse it -- most objectives should not need it.

    OBJECTIVE TO BREAK DOWN:
    "{objective}"

    CRITICAL EXAMPLES:
    Objective: "Check my system resources and then open notepad to take notes"
    Output:
    [
        {{"step_number": 1, "action": "system_command", "target": "check ram and cpu", "description": "Gathering hardware telemetry."}},
        {{"step_number": 2, "action": "open_app", "target": "notepad", "description": "Launching text editor for notes."}}
    ]

    Objective: "Book the cheaper flight"
    Output:
    [
        {{"step_number": 1, "action": "ask_user", "target": "Which two flights are you comparing, and do you have the prices?", "description": "Need flight details before proceeding."}}
    ]
    """

    try:
        response = ollama.chat(model=model_router.select_model("autonomous_workflow"), messages=[
            {'role': 'system', 'content': planner_prompt}
        ], format='json')

        plan = json.loads(response['message']['content'].strip())
        return plan
    except Exception as e:
        print(f"[Orchestrator Error] Failed to generate plan: {e}")
        return []


def _save_checkpoint(objective, plan, next_index, execution_summary):
    """Persists workflow state to disk so it can survive across process
    turns while Argus waits for the user to answer a clarifying question."""
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({
            "objective": objective,
            "plan": plan,
            "next_index": next_index,
            "execution_summary": execution_summary,
        }, f)


def has_pending_workflow():
    """True if there's a paused autonomous workflow waiting on user input."""
    return os.path.exists(CHECKPOINT_FILE)


def _clear_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)


async def _run_plan_from(objective, plan, start_index, execution_summary):
    """Runs plan steps starting at start_index. Pauses (saving a checkpoint)
    if it hits an ask_user step, otherwise runs to completion and returns
    the final triumphant summary."""
    for i in range(start_index, len(plan)):
        step = plan[i]
        if not isinstance(step, dict):
            print(f"[Orchestrator Warning] Skipping malformed step: {step}")
            continue

        step_num = step.get("step_number", i + 1)
        action = step.get("action", "casual_chat")
        target = step.get("target", "")
        desc = step.get("description", "Executing task")

        if action == "ask_user":
            try:
                import feature_toggles
                checkpointing_on = feature_toggles.is_enabled("workflow_checkpointing")
            except Exception:
                checkpointing_on = True

            if not checkpointing_on:
                # Toggle is off: don't pause/save state, just tell the user
                # the workflow needs more specific input and stop here.
                _clear_checkpoint()
                return f"I need more detail to continue — {target} (workflow checkpointing is currently off, so I can't pause and wait; ask again with that detail included)."

            print(f"\n[Step {step_num}] Pausing workflow -- needs clarification: {target}")
            _save_checkpoint(objective, plan, i + 1, execution_summary)
            return f"Hold on -- before I continue, {target}"

        print(f"\n[Step {step_num}] {desc} -> Executing: {action}({target})")

        result = run_local_command(action, target)
        print(f"[Step {step_num} Result]: {result}")
        execution_summary.append(f"Step {step_num} ({desc}): {result}")

        await asyncio.sleep(1.5)

    _clear_checkpoint()

    reporter_prompt = f"""
    You are Argus. You have just completed an autonomous multi-step workflow.
    Review the execution summary below and provide a concise, triumphant final summary to the user in 2 or 3 sentences maximum.

    OBJECTIVE: {objective}
    EXECUTION SUMMARY:
    {chr(10).join(execution_summary)}
    """

    try:
        report_response = ollama.chat(model=model_router.select_model("autonomous_workflow"), messages=[
            {'role': 'system', 'content': reporter_prompt}
        ])
        return report_response['message']['content'].strip()
    except Exception:
        return "Workflow complete. All steps executed successfully inside the matrix."


async def execute_autonomous_workflow(objective):
    """Loops through the generated plan, executes commands, and aggregates the results.
    May pause partway through and save a checkpoint if it needs to ask the user
    something -- see resume_autonomous_workflow()."""
    print(f"\n[Agent Core] Initializing Autonomous Workflow for Objective: {objective}")
    plan = await generate_execution_plan(objective)

    if not plan:
        return "I was unable to construct a stable execution plan for that objective."

    return await _run_plan_from(objective, plan, 0, [])


async def resume_autonomous_workflow(user_answer):
    """Resumes a paused workflow using the user's answer to the last
    ask_user step, then continues executing the remaining plan steps."""
    if not has_pending_workflow():
        return "There's no paused workflow waiting on you right now, macha."

    with open(CHECKPOINT_FILE, "r") as f:
        checkpoint = json.load(f)

    objective = checkpoint["objective"]
    plan = checkpoint["plan"]
    next_index = checkpoint["next_index"]
    execution_summary = checkpoint["execution_summary"]
    execution_summary.append(f"User clarification: {user_answer}")

    print(f"\n[Agent Core] Resuming Autonomous Workflow for Objective: {objective}")
    return await _run_plan_from(objective, plan, next_index, execution_summary)
