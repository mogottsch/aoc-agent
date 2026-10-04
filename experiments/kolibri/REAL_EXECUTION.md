# Real Kolibri execution and lifecycle

## Completed campaign (2026-10-04)

The user-approved real Kolibri campaign completed all 50 unique tasks (2022 and
2023, days 1–25). The final consolidated rows contain zero execution-error rows:
part 1 is correct on 46/50 tasks, part 2 on 40/50, and both parts on 39/50.
See [RESULTS.md](RESULTS.md) for public provenance and the
[repository benchmark table](../../README.md) for the generated comparison.

This was a multi-attempt campaign with checkpoint continuation, **not a fresh
single pass**. Completed non-error rows, including wrong answers, were retained;
execution-error rows were excluded from the continuation seed and retried.
The totals are conditional on this recovery policy. Zero errors in the final
rows does not mean the campaign had no failed attempts.

The actual serving context was **131,072 tokens**, not the original 32,768-token
preparation plan. The final isolated CPU runner had an **8 GiB memory limit**.
A **4 GiB per-process RLIMIT** was enabled only for the last campaign; the first
13 retained seed rows came from an earlier local runner without that RLIMIT.
Do not describe all 50 rows as having identical execution-memory isolation.
Model/tokenizer revisions, image pins and sampling configuration were retained.

The GPU instance was destroyed and its absence was confirmed by provider
readback. No live GPU is required to inspect the public result summary. Private
cleanup receipts remain private; process exit alone is never deletion proof.

## Artifacts and trust boundaries

- `real_lifecycle.py` implements the provider adapter, durable ownership-bound
  leases and independent watchdog. Private lease records are permission-restricted.
  Create-response ambiguity is reconciled before any second rental. Deletion
  rechecks ownership and reads provider inventory back; the provider does not
  offer conditional-delete/CAS guarantees.
- `real_controller.py` prepares the pinned serving image, authenticated TLS
  transport, isolated runner and incremental artifact export. It retains
  recoverable benchmark failures only inside the approved lifecycle boundaries.
- `real_transport.py` uses an ephemeral certificate as the sole trust anchor,
  fixed certificate SAN `kolibri.invalid`, disposable bearer authentication and
  a loopback proxy restricted to model discovery and chat completions. Redirects
  and proxy-environment routing are disabled.
- `real_runner.py` runs the allowlisted source/cache bundle inside the isolated
  runner and waits for trusted release before inference. It receives no provider,
  real AoC-cookie, personal or control-plane credentials. The offline AoC token
  is a non-secret schema placeholder.
- `checkpoint.py` validates configuration/pin compatibility and row identity,
  rejects duplicate/foreign/error seed rows and preserves completed wrong answers.
  Seed provenance records must accompany consolidated results.
- `real_resume.py` handles approved continuation, replay and stop actions.
  `real_extend.py` is an explicit extension path, not permission to silently
  change a deadline or start another rental.

The isolated runner uses non-root/read-only/drop-all/seccomp settings, no service
account token or host mounts, bounded temporary storage, resource quotas, pinned
CPU dependencies and a Job deadline. Package/control-plane egress is revoked
before release after exact positive/negative network controls. Serving egress is
pod/IP scoped: generated code can reach the same approved serving destination.
This is container isolation, not a VM-grade malicious-code sandbox.

Cached puzzle HTML is reduced to puzzle articles and answer paragraphs. No
checkout-wide copy, private environment, global results or control-plane code
belongs in the runner bundle. Provider credentials and private transport material
stay out of public artifacts. Public results must not include raw request logs,
certificates, tokens, leases, account balances, private hostnames or deployment IDs.

## Lifecycle and recovery contract

An independent off-host watchdog must survive controller termination. Initial
launch requires review, explicit spending approval, a freshly verified watchdog
receipt and a current offer including disk/download costs. A future campaign
requires new approval; the completed campaign does not authorize another rental.

Mandatory cleanup persists its intent before inventory lookup and must not be
blocked by an account-credit read failure. Empty inventory by itself cannot
resolve an ambiguous create or prove deletion. Terminal destruction requires a
successful explicit delete followed by ownership-checked absence readback.
Unresolved ownership or lost responses remain operator-reconciliation blockers.

Recoverable failed attempts may be retained for debugging only while ownership,
remaining deadline, credit reserve and hourly-rate gates remain valid. Preserve
original attempts and checkpoint provenance. Do not turn an infrastructure retry
into an answer-selection policy: keep all completed non-error rows, even wrong
ones. Full replay and checkpoint continuation are distinct operations and must
be labeled accordingly in any comparison.

At a mandatory termination boundary, GPU cleanup must not wait for Kubernetes
export/deletion. Evidence export and namespace cleanup may require separate
reconciliation. Controller death can stop export; a dead runner cannot recover
previously unexported temporary files. A stopped process/container/instance is
not provider destruction. Provider/API latency and storage/bandwidth charges
mean a watchdog is not a guaranteed hard financial cap.

## Offline review commands (repository root)

These commands exercise local tests or print plans; they do not authorize a new
rental. CPU preflight and executing lifecycle commands are deliberately omitted
from this public offline checklist because they change external state.

```sh
.venv/bin/python experiments/kolibri/real_controller.py
.venv/bin/python experiments/kolibri/real_lifecycle.py
AOC_SESSION_TOKEN=OFFLINE_NOT_A_COOKIE LOGFIRE_IGNORE_NO_CONFIG=1 \
  .venv/bin/python -m pytest tests experiments/kolibri/tests -q
.venv/bin/ruff check --config experiments/kolibri/cpu-ruff.toml \
  experiments/kolibri/cpu_*.py experiments/kolibri/tests/test_cpu*.py \
  experiments/kolibri/real_*.py experiments/kolibri/tests/test_real*.py
.venv/bin/ruff format --check --config experiments/kolibri/cpu-ruff.toml \
  experiments/kolibri/real_*.py experiments/kolibri/tests/test_real*.py
```

Original preparation checks use this directory as working directory because
its per-file Ruff patterns are cwd-sensitive:

```sh
../../.venv/bin/ruff check --config ruff.toml run.py serve.py verify_pins.py tests/test_prepare.py
../../.venv/bin/ruff format --check --config ruff.toml run.py serve.py verify_pins.py tests/test_prepare.py
```

Historical preparation test counts are not current verification receipts. Run
the complete suite, scoped lint and a full staged-content secret/privacy scan
before committing. Runtime observations from this campaign do not establish
all failure-mode guarantees; provider-CAS limitations, watchdog/API latency,
pod-shared serving egress and exporter loss on controller death remain relevant.
