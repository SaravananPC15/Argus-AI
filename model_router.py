"""
model_router.py — Feature 9: Model routing by task complexity.

Argus talks to several different Ollama models. Previously each file
hardcoded a model name inline, which made it hard to reason about the
speed/quality tradeoff or to swap models later. This module centralizes
that decision so it's made in one place based on what kind of work is
being done.

FAST_MODEL   — tiny/quick model for classification, short single-turn
                replies, and anything latency-sensitive (voice UX).
REASONING_MODEL — larger model for tasks that benefit from stronger
                reasoning: multi-step planning, RAG synthesis over
                document context, and final workflow reports.
VISION_MODEL — the multimodal model for screen/image understanding.

The control-center UI also lets the user manually pick a model, which
overrides the automatic complexity-based routing below when
feature_toggles.is_enabled("model_auto_routing") is False (or a manual
pick has been made). Selection persists to selected_model.json.

PROTOCOL SMART POWER THROTTLING integrates here too, via
get_generation_options() below: it asks power_throttle.py for the
current battery-scaled token budget and returns it as an Ollama
`options` dict ({"num_predict": N}) a caller can pass straight to
ollama.chat(..., options=...). HONEST SCOPE: this is opt-in, not
retrofitted across every existing ollama.chat() call site in this
project -- doing that safely across a dozen-plus call sites is a
bigger, riskier change than this pass covers. round_table.py's own
calls use it as a working example; extending it to more call sites
(brain.py's casual_chat reply, council.py's turns, etc.) is straight-
forward from here -- add `options=model_router.get_generation_options()`
to that call -- just not done blanket-wide in this pass.
"""

import json
import os

FAST_MODEL = "llama3.2:1b"
REASONING_MODEL = "llama3.1"
VISION_MODEL = "moondream"

AVAILABLE_MODELS = ["llama3.2:1b", "llama3.2", "llama3.1", "qwen2.5:0.5b", "moondream"]

_SELECTION_FILE = "selected_model.json"

# Actions that benefit from the larger reasoning model rather than the
# fast 1B classifier model, because the output quality directly affects
# what gets executed or reported back to the user.
_HEAVY_REASONING_ACTIONS = {
    "read_document",       # RAG synthesis over retrieved document chunks
    "autonomous_workflow",  # multi-step plan generation + final report
    "deep_research",       # summarizing multiple search results
}


def get_manual_model():
    """Returns the user's manually-selected model from the UI, or None
    if they haven't picked one (auto-routing applies)."""
    if not os.path.exists(_SELECTION_FILE):
        return None
    try:
        with open(_SELECTION_FILE, "r") as f:
            data = json.load(f)
        model = data.get("model")
        return model if model in AVAILABLE_MODELS else None
    except (json.JSONDecodeError, OSError):
        return None


def set_manual_model(model_name: str):
    if model_name not in AVAILABLE_MODELS and model_name is not None:
        raise ValueError(f"Unknown model '{model_name}'. Options: {AVAILABLE_MODELS}")
    with open(_SELECTION_FILE, "w") as f:
        json.dump({"model": model_name}, f)


def select_model(action: str = "", complexity_hint: str = "") -> str:
    """
    Returns the Ollama model name to use for a given action/task.

    action: one of brain.py's action strings (e.g. "casual_chat",
            "read_document", "autonomous_workflow", "vision_task", ...)
    complexity_hint: free-text hint ("heavy", "vision", "fast") for
            callers that don't map cleanly onto an action name.

    If the user has manually picked a model in the UI AND turned off
    auto-routing, that pick wins for everything except vision tasks
    (moondream is the only model in this project that can actually see
    an image, so vision_task always uses it regardless of the manual pick).
    """
    if action != "vision_task" and complexity_hint != "vision":
        try:
            import feature_toggles
            auto_routing_on = feature_toggles.is_enabled("model_auto_routing")
        except Exception:
            auto_routing_on = True

        manual = get_manual_model()
        if manual and not auto_routing_on:
            return manual

    hint = (complexity_hint or "").lower()
    if hint == "vision":
        return VISION_MODEL
    if hint == "heavy":
        return REASONING_MODEL
    if hint == "fast":
        return FAST_MODEL

    if action == "vision_task":
        return VISION_MODEL
    if action in _HEAVY_REASONING_ACTIONS:
        return REASONING_MODEL
    return FAST_MODEL


def get_generation_options(base_tokens: int = 512) -> dict:
    """Protocol Smart Power Throttling: returns an Ollama `options` dict
    with `num_predict` scaled down by power_throttle.py's current
    battery-based multiplier (or unscaled -- an empty dict, meaning
    "use Ollama's own default" -- if power_throttle.py isn't available
    or reports full power). Pass this to ollama.chat(..., options=...)
    at any call site you want power-aware; see this module's own
    docstring for why that's opt-in rather than blanket-applied."""
    try:
        import power_throttle
        state = power_throttle.read_power_state()
        if state["token_multiplier"] >= 1.0:
            return {}
        return {"num_predict": power_throttle.scale_tokens(base_tokens)}
    except Exception:
        return {}
