"""
tiled_attention.py — Protocol Flash-Attention Emulation (Tiled Attention, NumPy).

READ THIS BEFORE WIRING IT INTO ANYTHING ELSE.

Real FlashAttention (Dao et al., 2022) is fast because it's a fused CUDA
kernel that keeps the whole computation inside a GPU's on-chip SRAM,
avoiding round-trips to slower HBM memory. The speedup is fundamentally
a GPU-memory-hierarchy trick.

None of that applies here, and it's important to be upfront about it:
this project's actual LLM inference (every `ollama.chat(...)` call
across the whole codebase) happens inside the separate Ollama server
process, which already runs llama.cpp/ggml -- a properly optimized,
SIMD/thread-parallel C++ inference engine. A NumPy attention kernel
living in this Python process cannot make those calls faster, because
it never touches them; Argus doesn't run its own transformer forward
pass anywhere, so there is no model inference loop for this module to
plug into.

What DOES translate to plain NumPy/CPU is the actual algorithmic trick
underneath FlashAttention: **tiling with online softmax** -- computing
attention over the keys/values in chunks so you never allocate the full
(n_queries x n_keys) score matrix at once. That's a genuine peak-memory
reduction, independent of whether it's faster in wall-clock terms (for
small/medium n_keys it usually ISN'T -- chunking adds Python-loop
overhead a single vectorized matmul doesn't have). Run this file
directly to see real numbers on your machine rather than a flattering
claim:

    python tiled_attention.py --benchmark

WHERE THIS IS ACTUALLY USED IN ARGUS: round_table.py's agent-relevance
scoring (embed the task, embed each specialist's blurb, attend over the
roster to get a relevance-weighted distribution). That roster is ~8
agents, so tiling buys nothing there -- round_table.py correctly calls
the direct path. It's included here because it's the same underlying
`attention()` function, and because a personal project is a reasonable
place to have a correct, honestly-documented tiled implementation on
hand for the day you feed something a few thousand keys on an 8GB
machine.
"""

import numpy as np


def attention(query, keys, values, chunk_size=None, return_weights=True):
    """
    Computes softmax(Q K^T / sqrt(d_k)) V.

    query:  (d_k,) or (n_queries, d_k)
    keys:   (n_keys, d_k)
    values: (n_keys, d_v)

    chunk_size=None (default): direct, fully vectorized computation.
        Materializes the full (n_queries, n_keys) score matrix. Fastest
        for small/medium n_keys -- this is what round_table.py uses.

    chunk_size=<int>: online-softmax tiling (FlashAttention's actual
        algorithm, simplified: single-head, non-causal, inference-only,
        no backward pass needed here). Peak *working* memory for the
        score computation is bounded by O(n_queries * chunk_size)
        instead of O(n_queries * n_keys) -- matters once n_keys gets
        into the thousands. Pass return_weights=False to keep the
        entire call bounded (output-only); return_weights=True still
        assembles the full (n_queries, n_keys) array to hand back,
        because that's what a materialized weights array inherently is.

    Returns (output, weights) -- output is (d_v,) or (n_queries, d_v);
    weights is (n_keys,) or (n_queries, n_keys), or None if
    return_weights=False.
    """
    query = np.asarray(query, dtype=np.float64)
    keys = np.asarray(keys, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)

    single_query = (query.ndim == 1)
    if single_query:
        query = query[None, :]
    if keys.ndim != 2 or values.ndim != 2:
        raise ValueError("keys and values must be 2D (n_keys, dim)")
    if keys.shape[0] != values.shape[0]:
        raise ValueError("keys and values must have the same n_keys")

    n_keys, d_k = keys.shape
    scale = 1.0 / np.sqrt(d_k)

    if chunk_size is None or chunk_size >= n_keys:
        output, weights = _direct(query, keys, values, scale)
    else:
        output, weights = _tiled(query, keys, values, scale, chunk_size, return_weights)

    if not return_weights:
        weights = None
    if single_query:
        output = output[0]
        if weights is not None:
            weights = weights[0]
    return output, weights


def _direct(query, keys, values, scale):
    scores = (query @ keys.T) * scale                  # (n_q, n_k) -- materialized on purpose
    scores = scores - scores.max(axis=1, keepdims=True)  # numerically stable softmax
    exp_scores = np.exp(scores)
    weights = exp_scores / exp_scores.sum(axis=1, keepdims=True)
    output = weights @ values
    return output, weights


def _tiled(query, keys, values, scale, chunk_size, return_weights):
    n_q = query.shape[0]
    n_k, d_v = values.shape

    running_max = np.full((n_q, 1), -np.inf)
    running_sum = np.zeros((n_q, 1))
    running_out = np.zeros((n_q, d_v))

    # Pass 1: online softmax over chunks. At no point does this hold more
    # than one (n_q, chunk_size) score block -- this is the actual
    # memory-bounded property being claimed.
    for start in range(0, n_k, chunk_size):
        end = min(start + chunk_size, n_k)
        k_chunk = keys[start:end]
        v_chunk = values[start:end]

        scores = (query @ k_chunk.T) * scale            # (n_q, chunk) only
        chunk_max = scores.max(axis=1, keepdims=True)
        new_max = np.maximum(running_max, chunk_max)

        correction = np.exp(np.where(np.isneginf(running_max), -np.inf, running_max - new_max))
        exp_scores = np.exp(scores - new_max)

        running_sum = running_sum * correction + exp_scores.sum(axis=1, keepdims=True)
        running_out = running_out * correction + exp_scores @ v_chunk
        running_max = new_max

    output = running_out / running_sum

    if not return_weights:
        return output, None

    # Pass 2 (only if the caller wants the full weights back): re-derive
    # each chunk's normalized weights using the now-known true max/sum.
    # Still one chunk in memory at a time -- the *returned* array is
    # unavoidably (n_q, n_k) because that's what a full weights matrix is,
    # but nothing here ever builds the full SCORE matrix at once.
    weights = np.empty((n_q, n_k))
    for start in range(0, n_k, chunk_size):
        end = min(start + chunk_size, n_k)
        k_chunk = keys[start:end]
        scores = (query @ k_chunk.T) * scale
        weights[:, start:end] = np.exp(scores - running_max) / running_sum

    return output, weights


def _demo_equivalence(seed=0):
    """Sanity check: tiled and direct paths must agree to float precision.
    Run automatically under --selftest."""
    rng = np.random.default_rng(seed)
    n_q, n_k, d_k, d_v = 5, 137, 16, 24
    query = rng.normal(size=(n_q, d_k))
    keys = rng.normal(size=(n_k, d_k))
    values = rng.normal(size=(n_k, d_v))

    out_direct, w_direct = attention(query, keys, values, chunk_size=None)
    for chunk in (1, 7, 32, 200):  # 200 > n_k, exercises the "no tiling needed" branch too
        out_tiled, w_tiled = attention(query, keys, values, chunk_size=chunk)
        assert np.allclose(out_direct, out_tiled, atol=1e-9), f"output mismatch at chunk_size={chunk}"
        assert np.allclose(w_direct, w_tiled, atol=1e-9), f"weights mismatch at chunk_size={chunk}"
    print("[tiled_attention] Equivalence check passed: tiled output matches direct "
          "computation exactly (within float tolerance) for chunk_size in {1, 7, 32, 200}.")


def benchmark():
    """Prints an honest side-by-side of direct vs. tiled: wall-clock time
    AND peak memory, across a few sequence lengths, so the tradeoff this
    module's docstring describes is something you can see on your own
    machine instead of taking on faith."""
    import time
    import tracemalloc

    d_k, d_v, chunk = 64, 64, 256
    print(f"{'n_keys':>8} | {'direct time':>12} | {'tiled time':>12} | "
          f"{'direct peak':>12} | {'tiled peak':>12}")
    print("-" * 66)

    for n_k in (500, 5_000, 50_000):
        rng = np.random.default_rng(1)
        query = rng.normal(size=(d_k,))
        keys = rng.normal(size=(n_k, d_k))
        values = rng.normal(size=(n_k, d_v))

        tracemalloc.start()
        t0 = time.perf_counter()
        attention(query, keys, values, chunk_size=None)
        t_direct = time.perf_counter() - t0
        _, peak_direct = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        t0 = time.perf_counter()
        attention(query, keys, values, chunk_size=chunk, return_weights=False)
        t_tiled = time.perf_counter() - t0
        _, peak_tiled = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"{n_k:>8} | {t_direct*1000:>9.2f} ms | {t_tiled*1000:>9.2f} ms | "
              f"{peak_direct/1024:>9.1f} KB | {peak_tiled/1024:>9.1f} KB")

    print("\nRead this honestly: at small/medium n_keys, direct is usually as fast or")
    print("faster -- tiling's Python-loop overhead isn't free. The peak-memory column")
    print("is the real, provable win, and it's the one that matters if you ever need")
    print("to attend over more keys than comfortably fit in RAM at once.")


if __name__ == "__main__":
    import sys
    if "--benchmark" in sys.argv:
        _demo_equivalence()
        benchmark()
    else:
        _demo_equivalence()
        print("Run with --benchmark for the time/memory comparison.")
