"""
sequence_sharding.py — Protocol Dynamic Sequence Sharding.

For a system log or codebase too large to reasonably hand the model in
one shot, this splits it into shards at the CLEANEST boundary it can
find (never mid-function, never mid-log-entry if it can help it), runs
each shard through model_router.FAST_MODEL for a short "key facts from
this part" extraction (the map step), then merges those per-shard notes
into one answer with the larger reasoning model (the reduce step).

THE ACTUAL TECHNIQUE: this is map-reduce summarization -- a standard
pattern for handling inputs bigger than a model's usable context, not
anything novel. What this module actually contributes is the boundary
detection in shard_text() below, tried in this order:
  1. Valid Python -> shard on top-level def/class boundaries (via `ast`),
     so a shard never splits a function in half.
  2. Text that looks like timestamped log lines -> shard on log-entry
     boundaries, so a shard never splits one entry across two pieces.
  3. Anything else -> blank-line paragraph boundaries.
  4. Last resort -> plain line-count chunking (still never mid-line).
Consecutive shards share a couple of overlap lines so an idea that
straddles a boundary isn't lost entirely.
"""

import ast
import re

import model_router

DEFAULT_MAX_CHARS = 3000  # ~750 tokens/shard -- comfortable for FAST_MODEL's per-call context
_LOG_LINE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"),   # 2026-07-23 10:15:02 / ISO-ish
    re.compile(r"^\[\d{2}:\d{2}:\d{2}\]"),                     # [10:15:02]
    re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"),  # syslog: "Jul 23 10:15:02"
]


def _looks_like_python(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except (SyntaxError, ValueError):
        return False


def _python_boundaries(text: str):
    """Line numbers (0-indexed) where a top-level statement begins --
    valid shard-start points that never land inside a function/class body."""
    tree = ast.parse(text)
    return sorted({node.lineno - 1 for node in tree.body})


def _log_boundaries(text_lines):
    """Line numbers where a recognized log-entry timestamp starts, IF
    enough lines match one consistent pattern to trust it (otherwise
    returns None so the caller falls through to paragraph/line chunking
    instead of a boundary set that's mostly noise)."""
    for pattern in _LOG_LINE_PATTERNS:
        matches = [i for i, line in enumerate(text_lines) if pattern.match(line)]
        if len(matches) >= max(3, len(text_lines) // 20):  # at least ~5% of lines, min 3
            return matches
    return None


def _paragraph_boundaries(text_lines):
    return [i for i, line in enumerate(text_lines) if line.strip() == ""]


def _densify_boundaries(lines, boundaries, max_chars):
    """If any gap between two consecutive structural boundaries is so
    large that it would become an oversized shard entirely on its own
    (a format change partway through a real log file, one unusually
    huge function), inject additional line-count cut points into just
    that gap. Without this, boundary detection running out partway
    through a file produces one unboundedly large trailing shard --
    exactly what an early version of this function did on a log sample
    with a formatting inconsistency past line 100 during testing."""
    densified = list(boundaries)
    for start, end in zip(boundaries, boundaries[1:]):
        segment_chars = sum(len(l) + 1 for l in lines[start:end])
        if segment_chars <= max_chars * 2:
            continue
        chunk_chars = 0
        for i in range(start, end):
            if chunk_chars > max_chars:
                densified.append(i)
                chunk_chars = 0
            chunk_chars += len(lines[i]) + 1
    return sorted(set(densified))


def shard_text(text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap_lines: int = 2):
    """
    Splits `text` into a list of shard strings, each close to but not
    exceeding max_chars where a clean boundary allows it (a single
    oversized function/log entry can still exceed max_chars on its own
    -- this never cuts A LINE in half, but doesn't shatter one logical
    unit just to hit a size target either). Consecutive shards repeat
    `overlap_lines` lines of trailing context from the previous shard.
    """
    if len(text) <= max_chars:
        return [text]

    lines = text.split("\n")

    if _looks_like_python(text):
        boundaries = _python_boundaries(text)
    else:
        boundaries = _log_boundaries(lines)
        if boundaries is None:
            boundaries = _paragraph_boundaries(lines)
    if not boundaries or boundaries[0] != 0:
        boundaries = [0] + list(boundaries)
    boundaries = sorted(set(boundaries) | {len(lines)})
    boundaries = _densify_boundaries(lines, boundaries, max_chars)

    shards = []
    shard_start = 0
    chars_since_start = 0
    for i in range(1, len(boundaries)):
        segment_start, segment_end = boundaries[i - 1], boundaries[i]
        segment = lines[segment_start:segment_end]
        segment_chars = sum(len(l) + 1 for l in segment)

        if chars_since_start > 0 and chars_since_start + segment_chars > max_chars:
            # Close out the current shard before adding this segment.
            shard_lines = lines[shard_start:segment_start]
            shards.append("\n".join(shard_lines))
            shard_start = max(segment_start - overlap_lines, 0)
            chars_since_start = sum(len(l) + 1 for l in lines[shard_start:segment_start])

        chars_since_start += segment_chars

    if shard_start < len(lines):
        shards.append("\n".join(lines[shard_start:]))

    return [s for s in shards if s.strip()]


def _default_chat_fn(model: str, messages) -> str:
    import ollama
    response = ollama.chat(model=model, messages=messages)
    return response['message']['content'].strip()


def analyze_large_input(text: str, question: str, chat_fn=None, max_chars_per_shard: int = DEFAULT_MAX_CHARS) -> str:
    """
    Map-reduce analysis for input too large to reasonably fit in one
    call: shard (see shard_text), ask FAST_MODEL to extract key facts
    from each shard relevant to `question` (map), then merge those notes
    with the reasoning model into one answer (reduce). If the input is
    already small enough, skips the map-reduce machinery entirely and
    just asks directly -- sharding a short input would only add latency.

    chat_fn(model, messages) -> str is injectable (used by this file's
    own tests to run offline); defaults to a thin ollama.chat wrapper.
    """
    chat_fn = chat_fn or _default_chat_fn
    shards = shard_text(text, max_chars=max_chars_per_shard)

    if len(shards) == 1:
        return chat_fn(model_router.select_model("", complexity_hint="heavy"),
                        [{"role": "user", "content": f"{question}\n\n{text}"}])

    shard_notes = []
    for idx, shard in enumerate(shards):
        prompt = (f"You are looking at PART {idx + 1} of {len(shards)} of a larger document. "
                  f"Question to keep in mind: {question}\n\n"
                  f"Extract only the key facts from THIS part relevant to that question, as "
                  f"2-4 short bullet points. Don't try to answer the whole question yet -- "
                  f"other parts are being read separately.\n\n{shard}")
        note = chat_fn(model_router.FAST_MODEL, [{"role": "user", "content": prompt}])
        shard_notes.append(f"--- Part {idx + 1}/{len(shards)} ---\n{note}")

    merged_notes = "\n\n".join(shard_notes)
    final_prompt = (f"Question: {question}\n\nBelow are key facts extracted from "
                     f"{len(shards)} sequential parts of a larger document. Merge them "
                     f"into one direct, coherent answer.\n\n{merged_notes}")
    return chat_fn(model_router.select_model("", complexity_hint="heavy"),
                    [{"role": "user", "content": final_prompt}])


if __name__ == "__main__":
    python_sample = "\n\n".join(
        f"def function_{i}():\n    \"\"\"Docstring for function {i}.\"\"\"\n"
        f"    x = {i}\n    return x * {i}\n" for i in range(40)
    )
    shards = shard_text(python_sample, max_chars=400)
    print(f"[Python] {len(python_sample)} chars -> {len(shards)} shards, "
          f"sizes={[len(s) for s in shards]}")
    broken = sum(1 for s in shards if s.count("def ") and "return" not in s.split("def ")[-1])
    print(f"[Python] shards that look like they cut a function in half: {broken}")

    log_sample = "\n".join(
        f"2026-07-23 {10 + m // 60:02d}:{m % 60:02d}:00 INFO worker-{m % 4} processed job #{1000 + m}"
        for m in range(200)
    )
    shards = shard_text(log_sample, max_chars=800)
    print(f"[Log] {len(log_sample)} chars -> {len(shards)} shards, sizes={[len(s) for s in shards]}")

    # Stress test: boundary detection only covers the first half (format
    # changes, or a mixed-format file) -- this is what originally produced
    # one unboundedly large trailing shard before _densify_boundaries.
    messy_log = "\n".join(
        f"2026-07-23 10:{m:02d}:00 INFO job #{1000 + m}" if m < 50 else f"plain unstructured line {m}"
        for m in range(400)
    )
    shards = shard_text(messy_log, max_chars=800)
    sizes = [len(s) for s in shards]
    print(f"[Messy log] {len(messy_log)} chars -> {len(shards)} shards, "
          f"max shard size={max(sizes)} (budget={800})")
