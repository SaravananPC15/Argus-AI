"""
context_compactor.py — Protocol Semantic Context Compaction.

Before brain.py hands a long chat history or a pile of retrieved
document/log chunks to model_router.FAST_MODEL (llama3.2:1b -- a small
model where every token in its effective window costs you more, and
which degrades faster on noisy, filler-heavy context than the larger
reasoning model does), this scores every line's semantic weight and
drops the low-value ones, packing more actual signal into a smaller
token budget.

THE ACTUAL TECHNIQUE: this is extractive summarization by sentence
scoring -- the same family of idea as Luhn's 1958 algorithm, not
anything novel. Score = frequency-weighted content words (a short
built-in stopword list, no NLTK/spacy dependency needed for this), with
small boosts for things a casual filler line never has (numbers, file
paths, identifiers, capitalized proper nouns) and a guaranteed-keep
window at the START and END of the text (instructions and the most
recent turns matter disproportionately -- the "lost in the middle"
effect is well documented for long-context LLMs, and it's exactly the
middle this trims first). It reorders nothing -- a compacted transcript
should still read top-to-bottom in the order it happened.

This is deliberately a pure-Python heuristic, not another model call --
spending an LLM call to decide what to send to the LLM would eat any
latency this is meant to save.
"""

import math
import re

# A short, deliberately unglamorous stopword list -- common English
# function words AND casual conversational filler, since a raw
# grammatical stopword list alone still lets "got", "sure", "cool",
# "yeah" through, and those turned out (via _demo_equivalence-style
# testing below) to dominate scores in filler-heavy transcripts just as
# badly as "the" or "and" would. Not exhaustive; this doesn't need to be
# linguistically perfect, just good enough that discourse filler doesn't
# outscore actual content.
_STOPWORDS = frozenset("""
a an the and or but if then else so of to in on at for with from by as is
are was were be been being do does did done have has had having i you he
she it we they me him her us them my your his its our their this that
these those there here what which who whom whose when where why how
not no nor can could will would shall should may might must ok okay yeah
yep sure thanks thank please just also very really quite got get gets
cool alright fine sounds sound good great nice makes make sense understood
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")
_CODE_ISH_RE = re.compile(r"[_./]|[A-Z][a-z]+[A-Z]")  # snake_case/paths, camelCase/PascalCase
_NUMBER_RE = re.compile(r"\d")

CHARS_PER_TOKEN = 4  # same rough heuristic already used ad hoc elsewhere in this codebase


def _split_lines(text: str):
    # Keep the natural line/sentence structure of a transcript rather
    # than re-flowing it -- callers pass chat turns or doc chunks that
    # are already reasonably line-oriented.
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _content_words(line: str):
    return [w for w in _TOKEN_RE.findall(line.lower()) if w not in _STOPWORDS and len(w) >= 2]


def _line_document_frequencies(lines):
    """For each content word, how many DISTINCT lines it appears in --
    the "document frequency" half of TF-IDF. A word that shows up in
    many lines (even a content word like "got") is doing little to tell
    one line apart from another; a word that shows up in only one or two
    lines is specific, and specific is exactly what compaction should
    preserve."""
    doc_freq = {}
    for line in lines:
        for word in set(_content_words(line)):
            doc_freq[word] = doc_freq.get(word, 0) + 1
    return doc_freq


def _score_line(line: str, doc_freq: dict, n_lines: int) -> float:
    words = _content_words(line)
    if not words:
        return 0.0
    # Inverse-document-frequency, SUMMED (not averaged) across the line's
    # words: a line with several specific, rarely-repeated terms scores
    # higher than a line with one word that happens to repeat a lot --
    # summing (rather than averaging) is what makes an information-dense
    # line outscore a short repeated-filler line, which is the failure
    # mode this replaced a plain term-frequency-average for.
    idf_sum = sum(math.log((n_lines + 1) / doc_freq.get(w, 1)) + 1.0 for w in words)

    boost = 1.0
    if _NUMBER_RE.search(line):
        boost += 0.15  # numbers (error codes, counts, versions) are rarely filler
    if _CODE_ISH_RE.search(line):
        boost += 0.15  # looks like a path/identifier/CamelCase -- likely load-bearing
    if len(words) <= 1:
        boost -= 0.3   # single-content-word lines skew toward leftover filler

    return idf_sum * max(boost, 0.1)


def compact_context(text: str, target_tokens: int = 800, keep_edge_lines: int = 2) -> str:
    """
    Trims `text` down to roughly `target_tokens` (CHARS_PER_TOKEN heuristic)
    by dropping the lowest-scoring lines, keeping the rest in original
    order. The first and last `keep_edge_lines` lines are always kept
    regardless of score (instructions up top, most recent turns at the
    bottom). Returns `text` unchanged if it's already under budget.
    """
    target_chars = target_tokens * CHARS_PER_TOKEN
    if len(text) <= target_chars:
        return text

    lines = _split_lines(text)
    if len(lines) <= keep_edge_lines * 2:
        return text[:target_chars]  # too few lines to meaningfully drop any

    doc_freq = _line_document_frequencies(lines)
    scored = [(i, line, _score_line(line, doc_freq, len(lines))) for i, line in enumerate(lines)]

    protected = set(range(keep_edge_lines)) | set(range(len(lines) - keep_edge_lines, len(lines)))
    droppable = sorted((s for s in scored if s[0] not in protected), key=lambda s: s[2])

    kept = {i for i in protected}
    kept_chars = sum(len(lines[i]) for i in kept)
    seen_text = {lines[i].strip().lower() for i in protected}
    # Add droppable lines back in, HIGHEST score first, until we're at
    # budget -- skipping lines whose text (normalized) is already kept,
    # so multiple near-identical restatements don't all get selected and
    # crowd out other, distinct high-value lines (a real risk once a
    # transcript revisits the same point more than once).
    for i, line, _score in sorted(droppable, key=lambda s: -s[2]):
        normalized = line.strip().lower()
        if normalized in seen_text:
            continue
        if kept_chars + len(line) > target_chars:
            continue
        kept.add(i)
        kept_chars += len(line)
        seen_text.add(normalized)

    result_lines = [lines[i] for i in sorted(kept)]
    dropped_count = len(lines) - len(result_lines)
    if dropped_count > 0:
        return "\n".join(result_lines) + f"\n[...{dropped_count} lower-signal line(s) compacted out...]"
    return "\n".join(result_lines)


def compaction_stats(original: str, compacted: str) -> dict:
    """Small helper for logging/debugging: how much this actually saved."""
    orig_tokens = max(len(original) // CHARS_PER_TOKEN, 1)
    new_tokens = max(len(compacted) // CHARS_PER_TOKEN, 1)
    return {
        "original_tokens_est": orig_tokens,
        "compacted_tokens_est": new_tokens,
        "reduction_pct": round(100 * (1 - new_tokens / orig_tokens), 1),
    }


if __name__ == "__main__":
    sample = """
The user asked about the vector index. Sure, got it. Ok. Yeah understood.
The FAISS index at argus_docs.faiss currently holds 4213 vectors across 12 documents.
Sounds good. Thanks. Got it, makes sense.
Query latency for document_processor.query_documents() averages 340ms on this machine.
Ok cool. Yep. Sure thing. Got it.
The user then asked whether castellan.py's BLE scan interval could be reduced from 6.0 seconds.
Alright. Sounds fine. Yeah.
Reducing bleak's scan timeout below about 4 seconds risks missing intermittent BLE advertisements.
Ok thanks. Got it. Cool cool.
Finally the user asked to summarize today's changes for the log digest.
""" * 6  # repeat to force it over budget for the demo

    compacted = compact_context(sample, target_tokens=120)
    stats = compaction_stats(sample, compacted)
    print(f"Original: ~{stats['original_tokens_est']} tokens -> "
          f"Compacted: ~{stats['compacted_tokens_est']} tokens "
          f"({stats['reduction_pct']}% reduction)\n")
    print(compacted)
