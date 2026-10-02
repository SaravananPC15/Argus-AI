"""
slop_filter.py — Protocol No Slop.

Detects and strips generic AI-writing patterns from Argus's own
responses before they reach you: throat-clearing openers, faux-insight
setups, binary-contrast clichés, fake-profound endings, colon-reveal
setups, and formatting bloat (emoji headings, decorative bold).

WHERE THIS CAME FROM: inspired by petergyang/no-ai-slop, a real,
recent (July 2026) open-source pattern list that's genuinely well
documented. That project ships as a Claude-Code skill -- a prompt file
an agent like Claude Code interprets -- not a portable library, so
there's nothing to import. This is an independent implementation of
the same CATEGORY of detection (these are publicly documented,
widely-recognized AI writing tics, not anyone's proprietary code),
built as an actual Python module because that's what fits Argus's
architecture.

WHY THIS MATTERS MORE HERE THAN IT MIGHT ELSEWHERE: small local models
(llama3.2:1b, llama3.1:8b) lean on generic scaffolding MORE than large
frontier models do, not less -- it's a common fallback pattern when a
smaller model isn't confident what to say next. This is arguably more
useful on Argus's actual hardware than on whatever the original skill
was built for.

WHAT THIS DOES NOT DO: flatten Argus's actual personality. brain.py's
HUMAN_PERSONA_PROMPT deliberately asks for sarcasm, Tanglish, and
"punchy, cinematic" brevity -- none of that is slop, and the pattern
list below is scoped to avoid it (see _self_test's adversarial cases,
which specifically check that sarcasm/slang survive untouched).

TWO-TIER DESIGN: mechanical regex removal for patterns safe to strip
outright (filler openers/closers, formatting bloat) costs nothing --
no extra model call. Structural patterns (binary contrasts, colon
reveals, fake-profound endings) are harder to fix by deletion alone
without breaking the sentence, so those are DETECTED by regex but
FIXED by one small, targeted FAST_MODEL call -- and only when
something was actually found, so a clean response never pays for this
at all.
"""

import re

import model_router

# ---------------------------------------------------------------------
# Tier 1: mechanically safe to strip outright (no rewrite needed --
# removing these leaves a grammatically complete sentence/paragraph).
# ---------------------------------------------------------------------

_FILLER_OPENERS = [
    r"^here'?s the thing[,.:]?\s*",
    r"^let me be clear[,.:]?\s*",
    r"^i should note that\s*",
    r"^it'?s worth (noting|mentioning) that\s*",
    r"^to be (completely |totally )?honest[,.:]?\s*",
    r"^simply put[,.:]?\s*",
    r"^at the end of the day[,.:]?\s*",
]

_FILLER_CLOSERS = [
    r"\s*i hope this helps!?\.?$",
    r"\s*i hope this answers your question!?\.?$",
    r"\s*let me know if you (have any questions|need anything else)!?\.?$",
    r"\s*feel free to (ask|reach out) if.*?\.?$",
]

_FAUX_INSIGHT_SETUPS = [
    r"here'?s what nobody tells you[,:]?\s*",
    r"the part (everyone|most people) misses?( is)?[,:]?\s*",
    r"what nobody (tells you|talks about)[,:]?\s*",
]

# ---------------------------------------------------------------------
# Tier 2: structural patterns worth flagging, but a straight deletion
# would leave a broken sentence -- these trigger the LLM cleanup pass.
# ---------------------------------------------------------------------

_BINARY_CONTRAST = re.compile(
    r"\bit'?s not (?:just )?[^.!?]{3,40}\.\s*it'?s [^.!?]{3,60}[.!?]", re.IGNORECASE
)
_COLON_REVEAL = re.compile(
    r"\b(?:the (?:best|real|crazy|wild) part|here'?s the (?:kicker|twist))\s*:\s*[^.!?]{3,60}[.!?]",
    re.IGNORECASE,
)
_FAKE_PROFOUND_ENDING = re.compile(
    r"\b\w[^.!?]{3,40} isn'?t [^.!?]{3,30}\.\s*it'?s already [^.!?]{3,40}[.!?]", re.IGNORECASE
)

_EMOJI_HEADING = re.compile(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*\*\*.+\*\*\s*$", re.MULTILINE)
_EXCESSIVE_BOLD = re.compile(r"(\*\*[^*\n]{1,40}\*\*[.,;:!?]?\s*){4,}")  # 4+ short bolded fragments in a row


def _strip_regex_list(text: str, patterns: list) -> tuple:
    changes = []
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.group(0).strip():
            changes.append(match.group(0).strip())
            text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
    return text, changes


def detect_and_strip_mechanical(text: str) -> tuple:
    """Tier 1 only -- safe, instant, no model call. Returns (cleaned_text, changes)."""
    changes = []
    text, c = _strip_regex_list(text, _FILLER_OPENERS)
    changes += c
    text, c = _strip_regex_list(text, _FILLER_CLOSERS)
    changes += c
    text, c = _strip_regex_list(text, _FAUX_INSIGHT_SETUPS)
    changes += c

    if _EMOJI_HEADING.search(text):
        changes.append("emoji-decorated heading")
        text = _EMOJI_HEADING.sub(lambda m: m.group(0).split("**")[1], text)
    if _EXCESSIVE_BOLD.search(text):
        changes.append("excessive short-fragment bolding")

    return text.strip(), changes


def detect_structural(text: str) -> list:
    """Tier 2 -- patterns found but NOT auto-removed here (see module
    docstring: deleting these would break the sentence). Returns a list
    of {category, matched} for the caller to decide what to do with."""
    found = []
    for label, pattern in (
        ("binary_contrast", _BINARY_CONTRAST),
        ("colon_reveal", _COLON_REVEAL),
        ("fake_profound_ending", _FAKE_PROFOUND_ENDING),
    ):
        for match in pattern.finditer(text):
            found.append({"category": label, "matched": match.group(0).strip()})
    return found


def _default_chat_fn(model: str, messages) -> str:
    import ollama
    response = ollama.chat(model=model, messages=messages)
    return response["message"]["content"].strip()


def clean_response(text: str, chat_fn=None) -> dict:
    """
    The main entry point: runs Tier 1 (always, free), then Tier 2 ONLY
    if structural patterns were actually found -- a clean response never
    pays for the extra model call. Returns {"text", "changes",
    "used_llm_pass"} so a caller can log/inspect what happened, not just
    silently get different text back.
    """
    mechanical_text, changes = detect_and_strip_mechanical(text)
    structural = detect_structural(mechanical_text)

    if not structural:
        return {"text": mechanical_text, "changes": changes, "used_llm_pass": False}

    chat_fn = chat_fn or _default_chat_fn
    flagged_list = "\n".join(f"- \"{f['matched']}\"" for f in structural)
    prompt = f"""Rewrite ONLY the flagged lines below to remove the cliche AI-writing
pattern, keeping the same meaning and the original voice (casual, direct,
a little sarcastic is fine -- that's the personality, not the problem).
Do not add anything new, do not rewrite anything NOT flagged, do not add
commentary. Return the full text with just those spots fixed.

FLAGGED PATTERNS:
{flagged_list}

FULL TEXT:
{mechanical_text}"""

    try:
        cleaned = chat_fn(model_router.FAST_MODEL, [{"role": "user", "content": prompt}])
    except Exception as e:
        print(f"[No Slop] LLM cleanup pass failed ({e}); returning the mechanically-cleaned text as-is.")
        return {"text": mechanical_text, "changes": changes, "used_llm_pass": False}

    changes += [f"{f['category']}: \"{f['matched']}\"" for f in structural]
    return {"text": cleaned, "changes": changes, "used_llm_pass": True}


def _self_test():
    # 1. Filler openers/closers stripped mechanically, no LLM call needed.
    text = "Here's the thing, your script has a bug on line 12. I hope this helps!"
    result = clean_response(text)
    assert result["used_llm_pass"] is False
    assert "here's the thing" not in result["text"].lower()
    assert "i hope this helps" not in result["text"].lower()
    assert "bug on line 12" in result["text"]
    print(f"[1/5] Filler opener+closer stripped mechanically, no LLM call: OK -> {result['text']!r}")

    # 2. Faux-insight setup stripped.
    text = "Here's what nobody tells you: your battery drains faster on Chrome tabs."
    result = clean_response(text)
    assert "nobody tells you" not in result["text"].lower()
    assert "battery drains faster" in result["text"]
    print(f"[2/5] Faux-insight setup stripped: OK -> {result['text']!r}")

    # 3. Structural pattern (binary contrast) is DETECTED but needs the
    #    LLM pass -- verify with a mocked chat_fn so this doesn't need
    #    a live model, same pattern as this project's other tests.
    text = "It's not a bug. It's a feature that nobody asked for."
    calls = []
    def fake_chat(model, messages):
        calls.append((model, messages))
        return "Nobody asked for this feature, but here it is anyway."
    result = clean_response(text, chat_fn=fake_chat)
    assert result["used_llm_pass"] is True
    assert len(calls) == 1
    assert calls[0][0] == model_router.FAST_MODEL
    print(f"[3/5] Binary-contrast structural pattern triggers exactly one targeted FAST_MODEL call: OK")

    # 4. CRITICAL: Argus's actual personality/slang must survive untouched.
    #    This is the adversarial case that matters most -- a filter that
    #    also strips "macha"/sarcasm would be actively harmful here.
    persona_text = ("Systems nominal, macha. Your battery's at 74% and I've already throttled "
                     "the token budget, da -- seri, no drama needed.")
    result = clean_response(persona_text)
    assert "macha" in result["text"] and "da" in result["text"] and "seri" in result["text"]
    assert result["changes"] == []
    print(f"[4/5] Argus's own personality (Tanglish/sarcasm) passes through completely untouched: OK")

    # 5. Clean text with nothing wrong triggers zero changes and zero LLM calls.
    calls.clear()
    clean_text = "The fix is on line 12: you're comparing a string to an int."
    result = clean_response(clean_text, chat_fn=fake_chat)
    assert result["changes"] == [] and result["used_llm_pass"] is False and len(calls) == 0
    print(f"[5/5] Already-clean text: zero changes, zero model calls: OK")

    print("\nAll slop_filter self-tests passed.")


if __name__ == "__main__":
    _self_test()
