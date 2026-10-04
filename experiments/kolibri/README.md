# Kolibri-only AoC benchmark

**CPU controller/cleanup rehearsal:** the authorized homeserver CPU-only path is
implemented and empirically tested separately; see [CPU_REHEARSAL.md](CPU_REHEARSAL.md)
for reproducible commands, hardened boundaries, actual-agent crash cleanup evidence
and deferred limits. All exported CPU rows are explicitly synthetic, not Kolibri
benchmark results. See [REAL_EXECUTION.md](REAL_EXECUTION.md) for the real lifecycle.

**The user-approved real campaign completed on 2026-10-04:** 50 unique tasks,
zero execution-error rows in the final consolidated results, part 1 correct on
46/50, part 2 on 40/50, and both correct on 39/50. See [RESULTS.md](RESULTS.md)
for public provenance and the [repository benchmark table](../../results/README.md)
for the generated comparison. This was a multi-attempt checkpoint continuation,
not a fresh single pass: wrong-answer non-error rows were retained and excluded
execution-error rows were retried. Results are conditional on that recovery policy.
The GPU was destroyed and provider absence was confirmed.

Default preparation commands remain read-only and do not contact a model endpoint.
Local test fixtures and CPU rehearsal rows are wiring evidence, not real results.

## Safe commands

From the repository root, with the existing project `.venv`:

```bash
experiments/kolibri/run.sh
experiments/kolibri/run.sh dry-run --run-id kolibri-h200-01
experiments/kolibri/serve.sh
.venv/bin/python experiments/kolibri/verify_pins.py
LOGFIRE_IGNORE_NO_CONFIG=1 .venv/bin/python -m pytest tests experiments/kolibri/tests -q
.venv/bin/ruff check experiments/kolibri/run.py experiments/kolibri/serve.py experiments/kolibri/verify_pins.py experiments/kolibri/tests/test_prepare.py
.venv/bin/ruff check --config experiments/kolibri/cpu-ruff.toml experiments/kolibri/cpu*.py experiments/kolibri/tests/test_cpu*.py
.venv/bin/ruff format --check experiments/kolibri
bash -n experiments/kolibri/run.sh experiments/kolibri/serve.sh
```

`run.sh` defaults to offline preflight. It checks all 50 tasks (days 1–25 of
2022 and 2023): nonempty input and unsolved prompt files, parseable known part-1
answers, and part-2 answers except day 25. Cache contents and known answers are
never printed. Missing cache fails rather than fetching from AoC. `dry-run`
adds the complete ordered schedule and isolated output path; it creates no
results directory. Exit codes: 0 ready, 1 unavailable cache, 2 invalid input.
Read-only preflight is **not** proof of endpoint readiness or hardware capacity.

`serve.sh` prints a container command as JSON without running it. Only
`serve.sh --execute` starts Docker and downloads weights. It requires a dedicated
high-entropy `VLLM_API_KEY` in the environment. A missing key fails before Docker
is called. This helper creates no cloud instance.

`verify_pins.py` uses anonymous, bounded public metadata reads from GHCR,
Hugging Face, and GitHub. It checks manifest/config byte digests, amd64 platform,
entrypoint, image/CUDA version metadata, source release commit, model revision,
FP8 architecture, and sampling metadata. No image layers or safetensors are
requested. Default preflight only validates pin formats; run this separate
command for live verification. A changed tag produces an error; do not silently
re-pin during an experiment.

## Verified public pins

Public metadata was checked on 2026-10-03; `pins.json` is the machine-readable
record and `verify_pins.py` repeats the checks.

| Artifact | Pin |
|---|---|
| Image repository | `ghcr.io/aleph-alpha/aleph-alpha-inference` |
| Actual published version tag | `1.0.0-vllm0.29.0` |
| OCI index | `sha256:9a56ab1691f8bc8eb0fc82f0f534bfdd36da2218fa79b01b83448739fbda403b` |
| Linux/amd64 manifest | `sha256:ac93d782890eb942dd59afa7cee9fa1e681d09f63a0036b21ea7664a254ed7d5` |
| Image config | `sha256:528d42434a5e2c2f4cfbf7c72c01087dc3dad3788e9743b6a00ebd3410768145` |
| Plugin source release | `v1.0.0` at `049a6a7bd2405b27d6d280d256bd3d585191c7ae` |
| vLLM / CUDA image metadata | `0.29.0` / `13.0.2` |
| Model | `Aleph-Alpha/Kolibri-1` (FP8, public/ungated) |
| HF model and tokenizer revision | `e52eb4627d11516b0c01de49210ab5a4e4061444` |

The short image tags `v1.0.0` and `1.0.0` returned 404; do not use them. The
serving helper uses the immutable index digest, not `latest`. The image's
`org.opencontainers.image.revision` label is inherited from the **vLLM base**,
not proof of the plugin source commit. Image metadata and GitHub release are
verified separately; this is not a full binary/SBOM or signed-provenance audit.

Authoritative sources:
- [Pinned model card](https://huggingface.co/Aleph-Alpha/Kolibri-1/blob/e52eb4627d11516b0c01de49210ab5a4e4061444/README.md)
- [Pinned plugin README](https://github.com/Aleph-Alpha/aleph-alpha-inference/blob/049a6a7bd2405b27d6d280d256bd3d585191c7ae/README.md)
- [Pinned Dockerfile](https://github.com/Aleph-Alpha/aleph-alpha-inference/blob/049a6a7bd2405b27d6d280d256bd3d585191c7ae/Dockerfile)
- [Release reference API](https://api.github.com/repos/Aleph-Alpha/aleph-alpha-inference/git/ref/tags/v1.0.0)
- [HF revision metadata](https://huggingface.co/api/models/Aleph-Alpha/Kolibri-1/revision/e52eb4627d11516b0c01de49210ab5a4e4061444)

## Serving configuration and observed campaign

The model card gives an approximately 78 GB FP8 weight footprint and a single
H200 as a minimum supported configuration. Prep chooses tensor parallelism 1,
32,768-token context, one sequence, 90% GPU memory utilization, FP8 KV cache,
`kolibri1` reasoning and tool parsers, and automatic tool choice. Weight
quantization is read from the pinned FP8 model config. Generation defaults are
disabled (`--generation-config vllm`); the runner supplies all requested sampling
settings explicitly. This describes the original preparation helper, not the
actual campaign context: real serving used **131,072 tokens**. The final isolated
CPU runner had an **8 GiB memory limit** and the last campaign enabled a **4 GiB
per-process RLIMIT**. The first 13 retained seed rows came from an earlier local
runner without that RLIMIT. Do not attribute the last campaign's isolation to
all retained rows. Model/revision pins and sampling settings were unchanged.

The official image already has entrypoint `vllm serve`; do not prepend a second
`vllm serve` when using its default entrypoint. Docker publishes only
`127.0.0.1:8000:8000`; binding `0.0.0.0` is confined to the container. Do not use
host networking or expose an unauthenticated public port. `VLLM_API_KEY` is
passed by environment name, not secret-bearing argv. The completed campaign used
the separate real controller and authenticated TLS transport, not proof that
every legacy Docker-helper command or flag has been independently exercised.

For any newly approved campaign, verify on the chosen H200 host:
1. CUDA 13.0.2 compatibility, driver, actual GPU/VRAM, available disk for image,
   ~78 GB weights, cache and download overhead; inspect live bandwidth charges.
2. Image pull, plugin version/registration, `vllm serve --help`, all flags, pinned
   model/tokenizer downloads, successful model load, FP8 KV cache and memory headroom.
3. Authentication: unauthenticated requests rejected, authenticated `/v1/models`
   lists exactly the intended served model. A model listing is not inference proof.
4. Separately authorized real smoke: reasoning/content separation, function tools,
   required/auto tool choice, output schema, `top_k`, temperature/top-p, and request
   generation limit. Then test actual AoC tool execution. The completed campaign
   exercised real inference and AoC tools, not every possible mode or flag.
5. Context growth over agent turns, truncation, timeouts, generation-limit behavior,
   TTFT/tokens per second, and long-run stability. Do not assume the prep context fits every task
   or increase concurrency/context without measurements and renewed budget review.

## New execution: approval and lifecycle gates

Do **not** execute the following until the user separately approves spending and
real inference. The real controller and independent watchdog are documented in
[REAL_EXECUTION.md](REAL_EXECUTION.md); they do not guarantee a hard financial cap.

Before any rental, the operator must record live offer/host identity, single
H200 capacity, driver compatibility, reliability, location, total hourly/storage
rate, bandwidth/download charges, TTL and estimated worst-case spend. Check
existing instances and account credit through the trusted `vastctl` wrapper. Install
and test an **independent off-host destruction watchdog**, controlled on a trusted
machine, keyed to the returned instance ID. It must call provider destruction at
the approved deadline even if the runner, container or host fails, then read back
provider instance state to verify that ID is absent. An in-container timeout,
`docker --rm`, Ctrl-C, stopped process, or stopped instance is **not destruction**
and is not a hard spending boundary. Destroy immediately on failure and verify
absence again; include storage/bandwidth caveats in the final spend report.

Serving machine: transfer only public experiment serving files (`serve.py`,
`serve.sh`, `verify_pins.py`, `pins.json`) and a disposable serving key. Do not
transfer this repo's `.env`, AoC cookie, other provider keys, production files,
marketplace API key or entire benchmark cache to a marketplace host. Model
prompts may reach that host; the controller must contain no private workload.
The model is public, so HF credentials are unnecessary.

Legacy helper examples, **not the completed campaign launch recipe**:

```bash
# On the approved GPU machine, after the independent destroy watchdog is armed:
# Set VLLM_API_KEY securely in the process environment; do not print it or put it in argv.
./serve.sh --execute

# On the trusted controller, establish an authenticated SSH tunnel to the host's
# loopback serving port (replace the hostname/SSH port with verified actual values):
ssh -N -L 8000:127.0.0.1:8000 approved-gpu-host

# On an isolated controller, set KOLIBRI_API_KEY to the same disposable serving key.
experiments/kolibri/run.sh run --execute --run-id kolibri-h200-01
```

The tunnel is required: only literal `http://127.0.0.1:PORT/v1` or
`http://[::1]:PORT/v1` endpoints are permitted. Hosted provider URLs, DNS aliases,
userinfo, queries and fragments are rejected. Proxy environment variables and
redirect following are disabled for the model HTTP client. Avoid shell tracing.
The run disables external Logfire sending and never resolves other provider keys.
AoC stays offline; no puzzle answers are submitted to adventofcode.com.

**Local generated-code safety:** the existing AoC runner executes model-generated
Python in a local Jupyter kernel. This is not a complete security sandbox.
Before real inference, use a disposable, non-sensitive controller with only the
required offline caches and dedicated serving credential; do not expose a real
AoC cookie or private `.env`/filesystem to generated code. The core settings may
require `AOC_SESSION_TOKEN`; use a non-secret offline placeholder in that isolated
controller, not a real cookie. No marketplace/production credentials belong in
that environment. Do not run unreviewed generated code on the secret-bearing
working checkout.

## Runner integration and output isolation

`config.yaml` is a strict **sidecar** schema with `benchmark` and `model_settings`.
It is not an input to `aoc-agent benchmark`. The core CLI currently exposes only
`--config`; it has no day-subset, `--force`, or output-directory flags, and its
config lacks model settings. Core files were not changed.

The sidecar reuses `BenchmarkConfig`/model validation, the existing offline AoC
service, `run_agent` (including agent tools, prompts, local Jupyter execution),
answer scoring, JSONL schema and append/read helpers. An `OpenAIChatModel` receives
explicit model-default settings: temperature 1, top-p .97, top-k 128, high
reasoning with thinking enabled, 8,192 generation tokens and 1,800-second request
timeout. The installed adapter serializes the generation cap as
`max_completion_tokens`; a local mocked-transport test verifies the actual JSON
including reasoning chat-template kwargs. That test alone is not server acceptance;
the completed real campaign separately exercised the pinned model through its tools.

Full years run sequentially, with concurrency one. There is no hidden day subset.
A fresh simple run ID is required; existing directories and symlink/path escapes
are rejected. `--resume-from` supports a validated same-configuration/pin checkpoint
in a new output directory. Non-error seed rows are retained even when wrong;
excluded execution-error rows may be retried. Resume provenance and attempt evidence
must accompany interpretation of the final rows. There is no forced overwrite or
automatic global leaderboard update. Principal output artifacts are:

- `experiments/kolibri/runs/RUN_ID/manifest.json`: explicit effective configuration,
  immutable pins, running/complete/failed status and verified saved/error row counts.
- `experiments/kolibri/runs/RUN_ID/results.jsonl`: normal benchmark rows.

Resumed runs also preserve seed-manifest/provenance artifacts. Private attempt,
transport, lifecycle and cleanup evidence is not a public benchmark payload.

Unhandled inference/tool/infrastructure failures abort the run, mark its manifest
failed, close the model client and retain partial isolated rows. Error bodies and
credentials are not persisted by the failure handler. A hard kill may leave the
manifest running. A completed schedule is not a successful solve; inspect row
correctness/error fields. The runner does not pretend to match the core runner's
exception-to-row conversion/retry semantics. Review this difference before
comparing leaderboard totals.

Tests exercise read-only defaults, strict config, cache completeness, loopback
validation, isolation, serving plan, explicit execution/key gates, fixture agent
execution with a real local kernel, full-schedule orchestration, failure cleanup,
public metadata checks and real SDK request serialization using local fixtures.
Fixture rows remain in test temporary directories and are never benchmark data.
