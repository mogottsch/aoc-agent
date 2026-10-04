# Kolibri-1: completed campaign results

Completed **2026-10-04**, using real `Aleph-Alpha/Kolibri-1` inference on the
2022 and 2023 AoC days 1–25, sequentially in tool mode.

| Final consolidated outcome | Tasks |
|---|---:|
| Unique tasks | 50 |
| Execution-error rows | 0 |
| Part 1 correct | 46/50 |
| Part 2 correct | 40/50 |
| Both parts correct | 39/50 |

The [repository benchmark table](../../results/README.md) contains the generated score
and comparison; its generator and sanitized result rows are the authoritative
source for aggregate scoring. This document does not independently recompute it.
AoC day 25 has no part-2 puzzle; interpret the part-2 denominator using the
repository's existing benchmark scoring convention.

## Public provenance

- Model and tokenizer revision: `e52eb4627d11516b0c01de49210ab5a4e4061444`.
- Serving OCI index: `sha256:9a56ab1691f8bc8eb0fc82f0f534bfdd36da2218fa79b01b83448739fbda403b`.
- Image version: `1.0.0-vllm0.29.0`; plugin release `v1.0.0`, commit
  `049a6a7bd2405b27d6d280d256bd3d585191c7ae`.
- Actual serving context: **131,072 tokens** (the original preparation helper
  planned 32,768; that is not the campaign's runtime setting).
- Sampling remained temperature **1.0**, top-p **0.97**, top-k **128**, high
  reasoning with thinking enabled, **8,192** generation tokens, and **1,800 s**
  request timeout. Concurrency was one; no model/revision repinning was performed.
- The final isolated CPU runner had an **8 GiB memory limit**. A **4 GiB
  per-process RLIMIT** was enabled only for the last campaign. The first **13**
  retained seed rows originated in an earlier run without that RLIMIT.
- Completion and destruction are distinct: the GPU was explicitly destroyed
  and provider absence was confirmed. Private lifecycle receipts are not published.

The sanitized [campaign manifest](../../results/kolibri_manifest.json) records
model/config pins, final-result and seed hashes, and the recovery-policy caveat.

## Recovery-policy caveat

These are **multi-attempt, checkpoint-consolidated results**, not fresh
single-pass results. Completed non-error rows were retained, including wrong
answers. Execution-error rows were excluded from the continuation seed and
retried with the same pinned model and sampling configuration. Earlier failure
and seed provenance must be retained privately for audit.

The zero-error final artifact therefore describes the consolidated result set,
not the history of all attempts. Accuracy is conditional on this retry policy
and mixed execution-memory provenance. It must not be presented as a clean
single-pass success rate or uniform 4 GiB isolation across all 50 rows.

See [README.md](README.md) for pins and offline checks, and
[REAL_EXECUTION.md](REAL_EXECUTION.md) for lifecycle and trust boundaries.
No private account/instance IDs, hostnames, balances, infrastructure paths,
raw logs, certificates or token-bearing configurations belong in this summary.
