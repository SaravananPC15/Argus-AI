"""
round_table.py — Protocol Round Table (Multi-Agent Specialist Council).

Generalizes council.py's proven pattern -- several personas sharing the
same local model(s), talking to each other in turns, then a synthesis
pass -- from a fixed 2-persona design debate into a full roster of
specialists that Argus dynamically assembles per task. Two ways in,
matching the brief exactly ("only used when it has been assigned or get
a complex task"):

  1. EXPLICIT ASSIGNMENT -- "convene the round table on X" / "get the
     team on this" (routes to the "round_table" action below). Always
     runs, auto-selecting whichever roster members are actually
     relevant to X.
  2. AUTOMATIC ESCALATION -- agent_orchestrator.py calls
     maybe_auto_convene(objective) before planning an autonomous
     workflow. If the objective is genuinely multi-domain (spans
     several specialties rather than one), the round table runs first
     and its synthesis becomes extra planning context. A single-domain
     ask ("open notepad", "check my RAM") never comes close to the
     threshold and costs nothing extra.

HOW AGENTS ARE SELECTED (not just a keyword grep): the task and every
roster member's one-line blurb are embedded, then scored with
tiled_attention.attention() -- the task as the query, the roster as
keys/values. That's just a well-tested way to get a softmax-normalized
relevance distribution over 8 candidates; nothing about that scale needs
tiling (see tiled_attention.py's own docstring), so this calls it with
chunk_size=None (the direct path) on purpose. The SAME distribution's
normalized entropy doubles as the complexity signal maybe_auto_convene()
checks: weight concentrated on one agent = simple, single-domain task;
weight spread evenly = complex, multi-domain task. One mechanism, two
uses, no separate LLM call needed just to decide who should talk.

HONEST SCOPING ON "EXPERT MODELS": every agent below is a *persona* --
a distinct system prompt -- not a separately-loaded multi-GB model.
Loading eight different large models at once isn't realistic on this
project's 8GB RAM budget (the exact reasoning behind model_router.py's
FAST/REASONING split, and council.py's own docstring says the same
thing about its two personas). Specialization comes from the persona +
which parts of the codebase each one is written to care about. Turns
use the fast model by default, same as council.py's debate rounds; only
the final synthesis uses the larger reasoning model, because that's the
output actually being handed back as the plan. If your machine has the
RAM/VRAM to keep a second model loaded, point any agent at a real
specialized model you've pulled via AGENT_MODEL_OVERRIDES below --
the wake-it/use-it/sleep-it pattern is the same one model_router.py
already uses for the reasoning model.
"""

import re
import numpy as np
import ollama

import model_router
import tiled_attention

ARCHITECT_PERSONA = """You are 'The Architect' on Argus's specialist round table -- a bold,
creative systems designer. You favor elegant, forward-looking structure, aren't afraid to
introduce a new abstraction when it earns its keep, and push back when a plan feels too
timid or bolted-on. Stay concrete -- name the actual components/files/structure involved.
Keep each turn to 2-3 sentences, conversational, directly responding to what's just been said."""

DEBUGGER_PERSONA = """You are 'The Debugger' on Argus's specialist round table -- a skeptical
senior engineer who cares about edge cases, failure modes, and what breaks in production. You
push back on unnecessary complexity and ask the pointed question nobody wants to answer.
Keep each turn to 2-3 sentences, conversational, directly responding to what's just been said."""

SECURITY_ANALYST_PERSONA = """You are 'The Security Analyst' on Argus's specialist round table
-- you think in trust boundaries, what a careless default or an attacker on the same LAN could
do, and what happens when this runs unattended on someone's personal machine. Flag real,
specific risks (not generic "be careful"), and say plainly when something is actually fine.
Keep each turn to 2-3 sentences, conversational, directly responding to what's just been said."""

DATA_ENGINEER_PERSONA = """You are 'The Data Engineer' on Argus's specialist round table -- you
think about schema, storage, query patterns, and what happens once data outgrows a demo-sized
dataset. You call out where a JSON file should really be a database, or vice versa.
Keep each turn to 2-3 sentences, conversational, directly responding to what's just been said."""

SYSTEMS_ENGINEER_PERSONA = """You are 'The Systems Engineer' on Argus's specialist round table
-- you think about RAM, CPU, battery, latency, and concurrency on a single consumer laptop
(this whole project runs local models on an 8GB RAM budget). You flag anything that would
spike resource usage, block the main loop, or assume hardware the user may not have.
Keep each turn to 2-3 sentences, conversational, directly responding to what's just been said."""

RESEARCHER_PERSONA = """You are 'The Researcher' on Argus's specialist round table -- you think
about what's actually known versus assumed, what should be looked up rather than guessed, and
where a claim needs a source. You're comfortable saying "we don't actually know that yet."
Keep each turn to 2-3 sentences, conversational, directly responding to what's just been said."""

TUTOR_PERSONA = """You are 'The Tutor' on Argus's specialist round table -- you care whether a
plan or explanation would actually make sense to someone learning it for the first time. You
push for the plain-language version and flag jargon that's quietly covering for a gap in the
plan itself. Keep each turn to 2-3 sentences, conversational, directly responding to what's
just been said."""

PRAGMATIST_PERSONA = """You are 'The Pragmatist' on Argus's specialist round table -- you
represent the actual end user. You ask whether anyone would really use this, push to cut scope
back to what matters right now, and are the one voice allowed to say "this is overengineered
for what it needs to do." Keep each turn to 2-3 sentences, conversational, directly responding
to what's just been said."""

# key -> display name, persona (system prompt), and a short blurb used
# for the relevance-scoring embedding (and shown in the UI/logs).
AGENT_ROSTER = {
    "architect": {
        "display": "The Architect",
        "persona": ARCHITECT_PERSONA,
        "blurb": "systems design, structure, abstractions, how the pieces fit together",
    },
    "debugger": {
        "display": "The Debugger",
        "persona": DEBUGGER_PERSONA,
        "blurb": "edge cases, bugs, failure modes, code review, what breaks in production",
    },
    "security_analyst": {
        "display": "The Security Analyst",
        "persona": SECURITY_ANALYST_PERSONA,
        "blurb": "security, sandboxing, authentication, risk, privacy, trust boundaries",
    },
    "data_engineer": {
        "display": "The Data Engineer",
        "persona": DATA_ENGINEER_PERSONA,
        "blurb": "databases, schemas, indexing, storage, queries, data modeling",
    },
    "systems_engineer": {
        "display": "The Systems Engineer",
        "persona": SYSTEMS_ENGINEER_PERSONA,
        "blurb": "performance, RAM, CPU, battery, latency, concurrency, resource limits",
    },
    "researcher": {
        "display": "The Researcher",
        "persona": RESEARCHER_PERSONA,
        "blurb": "research, gathering information, evaluating sources, fact-checking, citations",
    },
    "tutor": {
        "display": "The Tutor",
        "persona": TUTOR_PERSONA,
        "blurb": "teaching, explaining clearly, studying, breaking concepts into steps",
    },
    "pragmatist": {
        "display": "The Pragmatist",
        "persona": PRAGMATIST_PERSONA,
        "blurb": "practicality, scope control, whether a real user actually wants this",
    },
}

# See the module docstring's "HONEST SCOPING ON EXPERT MODELS" section.
# Example: AGENT_MODEL_OVERRIDES = {"debugger": "qwen2.5-coder:7b"} --
# uncomment/edit and `ollama pull` the model first.
AGENT_MODEL_OVERRIDES = {}

ROUND_TABLE_COMPLEXITY_THRESHOLD = 0.85  # normalized entropy, 0..1 -- see _normalized_entropy


def _model_for(agent_key: str) -> str:
    return AGENT_MODEL_OVERRIDES.get(agent_key) or model_router.select_model("round_table")


def _tokenize(text: str):
    return re.findall(r"[a-z0-9]+", text.lower())


def _bag_of_words_embed(task: str, agent_keys):
    """Fallback relevance scoring for when the sentence-transformer
    embedder isn't available (e.g. torch/sentence-transformers not
    installed yet, or offline). Plain term-frequency vectors over the
    small vocabulary built from the roster's own blurbs -- less precise
    than real embeddings, but keeps agent selection working rather than
    failing closed."""
    corpus = {k: AGENT_ROSTER[k]["blurb"] for k in agent_keys}
    vocab = sorted(set(w for blurb in corpus.values() for w in _tokenize(blurb)))
    index = {w: i for i, w in enumerate(vocab)}

    def vec(text):
        v = np.zeros(max(len(vocab), 1))
        for w in _tokenize(text):
            if w in index:
                v[index[w]] += 1.0
        norm = np.linalg.norm(v)
        return v / norm if norm > 0 else v

    query_vec = vec(task)
    roster_vecs = np.array([vec(corpus[k]) for k in agent_keys])
    return query_vec, roster_vecs


def _embed_task_and_roster(task: str, agent_keys):
    """Prefers the project's existing sentence-transformer embedder
    (already resident in RAM for RAG/conversation-memory, so reusing it
    here is free -- same reasoning conversation_memory.py's docstring
    gives). Falls back to bag-of-words if that import fails. Returns
    (query_vec, roster_vecs, used_real_embedder) -- that third flag
    matters to maybe_auto_convene() below: the bag-of-words fallback is
    coarse enough that its complexity score shouldn't be trusted to
    spend extra local-inference calls on its own initiative."""
    try:
        import document_processor  # local import: don't force-load the ~80MB model
        query_vec = np.asarray(document_processor.embedder.encode([task])[0])
        roster_vecs = np.asarray(
            document_processor.embedder.encode([AGENT_ROSTER[k]["blurb"] for k in agent_keys])
        )
        return query_vec, roster_vecs, True
    except Exception as e:
        print(f"[Round Table] Embedder unavailable ({e}); using bag-of-words fallback for agent selection.")
        query_vec, roster_vecs = _bag_of_words_embed(task, agent_keys)
        return query_vec, roster_vecs, False


def _normalized_entropy(weights) -> float:
    """0 = all relevance weight on one agent (simple, single-domain task).
    1 = weight spread perfectly evenly across every agent (complex,
    multi-domain task). This is the standard softmax-distribution
    entropy, normalized by its own maximum (log(n)) so it's comparable
    regardless of roster size."""
    weights = np.clip(np.asarray(weights, dtype=np.float64), 1e-12, 1.0)
    entropy = -np.sum(weights * np.log(weights))
    max_entropy = np.log(len(weights))
    return float(entropy / max_entropy) if max_entropy > 0 else 0.0


def score_agents(task: str):
    """Returns (ranked, complexity, used_real_embedder): ranked is
    [(agent_key, weight), ...] sorted highest-relevance first across the
    WHOLE roster; complexity is the 0..1 normalized-entropy score
    described above; used_real_embedder tells the caller whether that
    complexity number came from real sentence embeddings or the coarser
    bag-of-words fallback (see maybe_auto_convene, which only trusts the
    former to make an autonomous decision)."""
    agent_keys = list(AGENT_ROSTER.keys())
    query_vec, roster_vecs, used_real_embedder = _embed_task_and_roster(task, agent_keys)

    if not np.any(query_vec):
        # No usable signal -- e.g. the bag-of-words fallback found zero
        # vocabulary overlap between the task and every agent blurb (a
        # short command like "open notepad" shares no words with any
        # specialist's technical blurb). A degenerate uniform softmax
        # would otherwise read as MAXIMUM entropy -- i.e. "extremely
        # complex, multi-domain" -- which is backwards: no signal should
        # never be more confident than a real signal. Treat it as zero
        # complexity (never auto-convenes) and hand back a flat ranking
        # rather than a misleading one.
        n = len(agent_keys)
        weights = [1.0 / n] * n
        ranked = sorted(zip(agent_keys, weights), key=lambda pair: -pair[1])
        return ranked, 0.0, used_real_embedder

    # values=roster_vecs is a placeholder -- we only use the attention
    # WEIGHTS (the relevance distribution), not the pooled output vector.
    # chunk_size=None on purpose: 8 keys is nowhere near where tiling
    # would matter (see tiled_attention.py's docstring).
    _, weights = tiled_attention.attention(query_vec, roster_vecs, roster_vecs, chunk_size=None)
    ranked = sorted(zip(agent_keys, weights.tolist()), key=lambda pair: -pair[1])
    complexity = _normalized_entropy(weights)
    return ranked, complexity, used_real_embedder


def select_relevant_agents(task: str, min_agents: int = 2, max_agents: int = 4):
    """Picks 2-4 roster members: always the top match, plus any others
    within half the top agent's relevance weight, capped at max_agents.
    Returns (selected_keys, complexity, used_real_embedder)."""
    ranked, complexity, used_real_embedder = score_agents(task)
    top_weight = ranked[0][1]
    selected = [ranked[0][0]]
    for key, weight in ranked[1:]:
        if len(selected) >= max_agents:
            break
        if len(selected) < min_agents or weight >= 0.5 * top_weight:
            selected.append(key)
    return selected, complexity, used_real_embedder


def run_round_table(topic: str, agent_keys, rounds: int = 1):
    """Runs the discussion and returns (transcript, synthesis).
    transcript: [{"speaker", "agent_key", "text"}, ...] in speaking order.
    Each agent speaks once per round; after each turn, every OTHER
    selected agent gets that turn's text queued as their next prompt, so
    by the time it's your turn you're responding to the accumulated
    table, not just the opening topic -- the same "respond to what was
    just said" pattern council.py uses for its two personas, generalized
    to however many are seated this time."""
    agent_keys = list(agent_keys) or ["pragmatist"]  # always have someone

    histories = {key: [{"role": "system", "content": AGENT_ROSTER[key]["persona"]}] for key in agent_keys}
    transcript = []

    opening = (f"Round Table topic: {topic}\n\n"
               f"This is a multi-specialist discussion. Give your opening take in "
               f"2-3 sentences from your specific angle.")
    for key in agent_keys:
        histories[key].append({"role": "user", "content": opening})

    for _round in range(max(rounds, 1)):
        for key in agent_keys:
            response = ollama.chat(model=_model_for(key), messages=histories[key],
                                    options=model_router.get_generation_options(base_tokens=200))
            text = response['message']['content'].strip()
            display = AGENT_ROSTER[key]["display"]
            transcript.append({"speaker": display, "agent_key": key, "text": text})
            histories[key].append({"role": "assistant", "content": text})

            for other_key in agent_keys:
                if other_key == key:
                    continue
                histories[other_key].append({
                    "role": "user",
                    "content": (f"{display} just said: {text}\n\n"
                                 f"Your reaction in 2-3 sentences -- agree, disagree, "
                                 f"or add what they missed?"),
                })

    discussion_text = "\n".join(f"{turn['speaker']}: {turn['text']}" for turn in transcript)
    synthesis_prompt = f"""
    A round table of specialists just discussed this: {topic}

    Read their exchange and write a decisive final answer in 4-6 sentences: what to
    actually do, which specialist's concern should win where they disagreed, and why.
    Be concrete, not wishy-washy -- this becomes the actual plan.

    DISCUSSION TRANSCRIPT:
    {discussion_text}
    """
    synthesis_response = ollama.chat(
        model=model_router.select_model("", complexity_hint="heavy"),
        messages=[{'role': 'system', 'content': synthesis_prompt}],
        options=model_router.get_generation_options(base_tokens=400),
    )
    synthesis = synthesis_response['message']['content'].strip()
    return transcript, synthesis


def handle_round_table_request(topic: str) -> str:
    """Entry point for executor.py's 'round_table' action -- explicit
    assignment, always convenes regardless of which scoring path picked
    the roster (a human explicitly asked, so an imperfect fallback
    selection is a minor inconvenience, not a runaway-cost risk)."""
    print(f"[Round Table] Convening on: {topic}")
    try:
        agent_keys, complexity, _used_real_embedder = select_relevant_agents(topic)
        names = ", ".join(AGENT_ROSTER[k]["display"] for k in agent_keys)
        print(f"[Round Table] Selected: {names} (relevance-spread score: {complexity:.2f})")
        transcript, synthesis = run_round_table(topic, agent_keys, rounds=2)
        for turn in transcript:
            print(f"  [{turn['speaker']}]: {turn['text']}")
        return f"Round Table convened -- {names}. Verdict: {synthesis}"
    except Exception as e:
        print(f"[Round Table Error]: {e}")
        return "The round table session crashed before reaching a verdict."


def maybe_auto_convene(objective: str):
    """Called by agent_orchestrator.py before planning an autonomous
    workflow. Returns a synthesis string to use as extra planning
    context if the objective is complex/multi-domain enough to cross
    ROUND_TABLE_COMPLEXITY_THRESHOLD, else None. This plus the explicit
    action above are the ONLY two ways the round table runs -- a plain
    single-domain ask never comes close and costs nothing extra.

    Deliberately requires the REAL embedder (used_real_embedder=True),
    not the bag-of-words fallback: this path spends extra local-inference
    calls on its own initiative with no human in the loop approving it,
    so it only acts on the higher-confidence signal. If the fallback is
    what's active, the normal single-agent planner just runs unassisted
    -- exactly what would have happened before this protocol existed."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("round_table"):
            return None
    except Exception:
        pass

    try:
        agent_keys, complexity, used_real_embedder = select_relevant_agents(objective)
        if not used_real_embedder:
            print("[Round Table] Auto-convene skipped: only the bag-of-words fallback "
                  "is available right now, and its complexity signal isn't trusted "
                  "for an unattended decision (see maybe_auto_convene's docstring).")
            return None
        if complexity < ROUND_TABLE_COMPLEXITY_THRESHOLD:
            return None
        names = ", ".join(AGENT_ROSTER[k]["display"] for k in agent_keys)
        print(f"[Round Table] Auto-convening (spread score {complexity:.2f} >= "
              f"{ROUND_TABLE_COMPLEXITY_THRESHOLD}): {names}")
        _, synthesis = run_round_table(objective, agent_keys, rounds=1)
        return synthesis
    except Exception as e:
        print(f"[Round Table] Auto-convene skipped (error: {e})")
        return None
