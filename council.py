"""
council.py — Protocol Multi-Agent Council (Local Dialogue Matrix).

Runs two separate chat threads against the same local Ollama model but
with different system-prompt personas — a strict debugger/skeptic and a
creative architect — and has them go back and forth a few rounds on a
design question before a final synthesis step. This is cheap to do
locally since both personas can share the fast model; it's really a
prompting pattern, not two different model weights.

Useful for "argue this out before I write code" style requests, and the
final synthesis can be handed straight to ghost_type or read aloud.
"""

import ollama
import model_router

ARCHITECT_PERSONA = """You are 'The Architect' — a bold, creative software designer.
You favor elegant, forward-looking designs, are willing to introduce new
abstractions, and push back when a design feels too conservative. Keep
each turn to 2-3 sentences, conversational, and directly respond to what
The Debugger just said."""

DEBUGGER_PERSONA = """You are 'The Debugger' — a strict, skeptical senior engineer.
You care about edge cases, simplicity, and maintainability. You push back
on unnecessary complexity and ask pointed questions. Keep each turn to
2-3 sentences, conversational, and directly respond to what The Architect
just said."""


def run_council(topic: str, rounds: int = 3):
    """Runs the debate and returns (transcript, final_synthesis).
    transcript is a list of {"speaker", "text"} dicts in order."""
    model = model_router.select_model("multi_agent_council")
    transcript = []

    architect_history = [{"role": "system", "content": ARCHITECT_PERSONA}]
    debugger_history = [{"role": "system", "content": DEBUGGER_PERSONA}]

    opening = f"Design topic: {topic}\n\nArchitect, open with your initial proposal."
    architect_history.append({"role": "user", "content": opening})

    last_message = None
    speaker = "architect"

    for _ in range(rounds * 2):
        if speaker == "architect":
            response = ollama.chat(model=model, messages=architect_history)
            text = response['message']['content'].strip()
            transcript.append({"speaker": "The Architect", "text": text})
            architect_history.append({"role": "assistant", "content": text})
            debugger_history.append({"role": "user", "content": f"Architect says: {text}\n\nYour rebuttal or question?"})
            speaker = "debugger"
        else:
            response = ollama.chat(model=model, messages=debugger_history)
            text = response['message']['content'].strip()
            transcript.append({"speaker": "The Debugger", "text": text})
            debugger_history.append({"role": "assistant", "content": text})
            architect_history.append({"role": "user", "content": f"Debugger says: {text}\n\nYour response?"})
            speaker = "architect"
        last_message = text

    # Final synthesis using the reasoning model, since this benefits from
    # actually weighing both sides rather than a quick classification.
    debate_text = "\n".join(f"{t['speaker']}: {t['text']}" for t in transcript)
    synthesis_prompt = f"""
    Two engineers just debated a design ({topic}). Read their exchange and
    write a concise final design decision in 3-4 sentences: what to build,
    what tradeoff was accepted, and why. Be decisive, not wishy-washy.

    DEBATE TRANSCRIPT:
    {debate_text}
    """
    synthesis_response = ollama.chat(
        model=model_router.select_model("", complexity_hint="heavy"),
        messages=[{'role': 'system', 'content': synthesis_prompt}]
    )
    final_synthesis = synthesis_response['message']['content'].strip()

    return transcript, final_synthesis


def handle_council_request(topic: str) -> str:
    """Entry point for executor.py's 'multi_agent_council' action."""
    print(f"[Council] Convening the council on: {topic}")
    try:
        transcript, synthesis = run_council(topic, rounds=3)
        for turn in transcript:
            print(f"  [{turn['speaker']}]: {turn['text']}")
        return f"The council debated it out, macha. Verdict: {synthesis}"
    except Exception as e:
        print(f"[Council Error]: {e}")
        return "The council session crashed before reaching a verdict."
