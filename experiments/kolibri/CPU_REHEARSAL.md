# CPU-only controller and independent cleanup rehearsal

This is **not a Kolibri benchmark** and has no Vast adapter, real provider credential,
GPU resource, weights, rental, or real inference. It reuses the real AoC agent,
`run_day`, offline data service, PydanticAI tool protocol, Jupyter executor and
benchmark JSONL schema with a deterministic `FunctionModel` explicitly labeled
`SYNTHETIC_CPU_FIXTURE_NOT_KOLIBRI`.

## Reproduce

From the repository root, using the existing Python >=3.13 environment:

```bash
uv run --frozen python experiments/kolibri/cpu_rehearsal.py                 # plan only, no writes
uv run --frozen pytest tests experiments/kolibri/tests -q                  # offline tests
uv run --frozen ruff check --config experiments/kolibri/cpu-ruff.toml \
  experiments/kolibri/cpu*.py experiments/kolibri/tests/test_cpu*.py
uv run --frozen python experiments/kolibri/cpu_rehearsal.py --execute-cpu   # authorized CPU rehearsal
```

Execution requires `kubectl` and the configured operator kubeconfig on the
**trusted operator**.
Nothing in a pod receives that kubeconfig, a service-account token or a provider
credential. The script picks a fresh `kolibri-cpu-*` namespace, refuses reuse,
creates only that namespace's bounded resources, records exact-target read-backs,
and reconciles an attempted namespace create in `finally`, even if the API accepted
it but the client timed out. Cleanup checks the exact name/unique ownership label,
binds the UID, and submits DELETE with UID/resourceVersion preconditions. A known
UID replacement or foreign label is preserved, not deleted. Cleanup failures mark
the summary failed and retain the original failure type; absence must be read back.
It rejects optimized
Python, because its assertions are verification gates. It never invokes `vastctl`,
`vastai`, cloud launch APIs, Docker builds, public ingress, GitOps writes or Git.

The runner intentionally exits **42 after exporting its successful synthetic
agent/Jupyter result**, before the fake resource deadline. Its Job is therefore
`Failed` by design. The watchdog's separate Job succeeds after cleanup. The
rehearsal's `status=passed` requires both facts; it does not reinterpret the runner
Job as successful.

## Runtime boundary

- Anonymous public official Python 3.13 slim image, immutable amd64 manifest:
  `python:3.13-slim-bookworm@sha256:88310c082760d93ac7c74d579e95e53a4ab6ea52dd8901abc61a103daf488ac4`.
- `cpu-runtime.lock`: 86 pinned public wheel dependencies, selected from the
  repository's `uv.lock` for Linux/Python 3.13. Includes OpenAI/Google SDK imports
  required transitively by existing AoC model-factory imports, **not permission
  to call those SDKs**. pip uses `--require-hashes --only-binary=:all:`.
- A ConfigMap transfers only `src/aoc_agent/**/*.py`, four experiment runtime
  scripts plus shared TCP-probe helper and the dependency lock. No `.env`, trusted checkout mount, actual AoC
  cache, private inputs, hostPath, PVC, credential Secret or production workspace.
- All containers/init containers UID/GID 10001, seccomp RuntimeDefault, dropped
  capabilities, no privilege escalation, read-only root, no host namespaces,
  no service-account token, explicit resource bounds, no restarts.
- Namespace admission is Pod Security `restricted`. Quota: at most 2 CPU limits,
  2Gi memory limits, 4Gi ephemeral-storage limits, 6 pods, 3 Jobs, 1 Service,
  zero PVCs and zero Secrets. Runner limit: 1 CPU/1Gi/2Gi ephemeral storage;
  provider and watchdog each 100m/128Mi/128Mi. Job deadlines 600/600/150 seconds.
- Default-deny ingress/egress. Runner can reach only fixture port 8080 and cluster
  DNS. Watchdog can reach provider port 8081 and DNS. Provider cannot initiate
  egress. No LoadBalancer, NodePort or ingress.
- During **trusted dependency installation only**, runner pod has temporary TCP
  443 egress to resolved public `pypi.org`/`files.pythonhosted.org` IPv4 /32s.
  Model-generated code does not run then: runner waits on an operator release
  gate. Operator deletes the install policy and reads back absence. While the
  gate remains closed, temporary policies allow **only exact discovered IP/ports**
  (including Service DNAT backends) for trusted TCP-connect-only positive controls.
  Control probes make no TLS/HTTP/authenticated requests to Kubernetes or the real broker.
  Operator revokes both control policies, reads back absence of all temporary
  policies, and requires fresh negative probes to match the positive controls'
  exact names/IPs/ports. The same controls are checked in the real Jupyter kernel.
  DNS errors, network-unavailable errors, missing/mismatched controls and unexpected
  errors fail closed; a socket exception alone is never isolation success.
  Empty public-IP allowlists are rejected rather than rendering unrestricted 443.
  NetworkPolicy is IP/port scoped,
  not hostname/TLS validation; shared public CDN addresses are broader than a
  single hostname. DNS is still permitted. IP rotation fails closed and may
  require a fresh rehearsal; do not broaden to unrestricted Internet access.
- Service IP/ports and ready backend IP/ports are discovered read-only from exact
  Kubernetes and broker Service/Endpoints objects, not guessed. Live broker ingress
  admits only existing production callers; dedicated-namespace egress permission
  cannot make that destination positively reachable. Both broker flows are retained
  as **unverified isolation observations**, never included in the positive-control
  success set. No production policy is changed and no production caller is spoofed.
- pip extraction uses the bounded `/work` volume, **not** the runtime's 128Mi
  `/tmp`. A retained failed run demonstrates why this separation matters.

## Cleanup contract

`cpu_watchdog.py` accepts only strict fake records: exact provider/instance/owner/
lease/creation/deadline fields, validated fake ID prefixes, finite timestamps,
and a maximum 600-second lifetime. Default is dry-run without any provider call.
Execution must use `--execute-fake`; only exact fake service/loopback endpoints
are accepted, proxies and redirects are disabled. There is no generic provider
selection or real credential path.

The immutable `cpu-record` ConfigMap is mounted only on provider and watchdog,
not runner; it exists independently of runner process lifetime. Each due pass
reads the exact instance, compares its full ownership/incarnation binding,
conditionally deletes using the same binding and **reads it again**. A delete
acknowledgement while the resource remains returns `retry`, never success.
Transient errors return `retry`; every retry rechecks binding, and mismatches
fail closed. The fake HTTP API atomically checks the expected binding on DELETE.
The Job is bounded to 120 seconds of polling plus Kubernetes's 150-second deadline.

Live fake API faults: first delete returns 503; second acknowledges but leaves
resource present; third actually deletes. A foreign resource remains untouched.
Final success requires exact instance GET returning 404 plus the provider's
inventory showing the target absent and foreign resource retained.

This is a rehearsal, not production durability: the fake provider's inventory is
in memory; provider/watchdog restart resilience, provider eventual consistency,
real identity revalidation, hard budget enforcement and reconciliation after
trusted-control-plane loss remain future work.

## Existing broker discovery and reuse decision

Read-only inspection of an existing compute broker and its deployment topology
found provider-factory injection, independent database-backed cleanup, bounded
instance destruction, inventory read-back and audit events. Its advertised job
contract covered a different workload rather than general AoC instance registration.
Source inspection alone was not treated as attestation of the live image's contents.

Reusing the production API would require new profile/contracts/database/provider
activation outside this task's approval. Importing its default watchdog CLI is
unsafe for a fake-only test. Consequently this directory adds only a small
**fake-only ownership/deadline rehearsal**, not another generic broker. Future
real lifecycle integration belongs in the existing trusted broker, not this
runner. Live broker UID/generation/spec hash are identical before and after each
rehearsal. No production API writes or production credentials were used.

## Empirical evidence

Latest passing review-corrected actual-agent-crash run:
`evidence/kolibri-cpu-91f29b51cfb0/`.

- Actual agent executed `execute_python` in a real Jupyter kernel, returned sum
  3/count 2 for public synthetic input and saved one explicitly labeled JSONL row.
- UID 10001 and service-account token absent inside that kernel.
- Allowed fixture HTTP worked. **Four exact flows** connected under the temporary
  TCP-only control allowance, then were refused after revocation in both the
  operator's fresh probes and Jupyter: the Kubernetes Service and API backend,
  the fake control Service, and a public PyPI endpoint. Targets were discovered
  for that run rather than hardcoded.
- Real broker Service and ready backend failed to connect **in both phases**.
  `unverified-broker-probes.json` explicitly
  records `isolation_proven=false`; this is not runner-egress isolation proof.
- Actual agent process then exited 42. Separate watchdog waited until the recorded
  deadline, retried the two injected provider faults and verified exact absence.
- Namespace was deleted and read back absent. Production broker spec unchanged.

Files include `summary.json`, `runner.log`, `watchdog.log`, `provider.log`,
`install.log`, `synthetic-results.jsonl`, `live-pods.json`, `live-jobs.json`,
`runtime-networkpolicies.json`, requested manifests, bundle digests, command audit,
pre-release probes, positive controls, target discovery (including broker ingress
policies), control policies, unverified broker observations, initial/final fake
inventories, exact-instance 404 read-back, source digests and final verification log.

Previous `evidence/kolibri-cpu-2356cd12fbe7/` proves the old synthetic crash/cleanup
path only. Its negative-only socket observations lacked same-destination positive
controls and **do not establish isolation**. It is retained as historical evidence,
not relabeled as verification of the corrected source.

Earlier smoke `evidence/kolibri-cpu-067adbdfa1cb/` used a separate synthetic crash
Job and is not the stronger actual-agent crash proof. The retained failed run
`evidence/kolibri-cpu-f8b390762c16/` was evicted because pip extraction temporarily
exceeded runtime `/tmp`'s 128Mi emptyDir limit. Its namespace was also removed;
regression test and final passing recipe move installation temp files to `/work`.

## Deferred limits

- Containers/NetworkPolicies are not VM-grade isolation for malicious generated
  code. These probes prove only the exact tested flows, not every possible node,
  DNS, kernel, CNI or future network path. Runtime permits DNS and fixture access.
- Synthetic callbacks and their token accounting are not real model inference,
  a Kolibri solve, model quality, throughput or paid token usage.
- Fake API deletion is not Vast deletion/billing proof. A timer is not a hard
  financial cap; actual provider ownership, destroy semantics, delayed inventory,
  storage/bandwidth charges and independent durable watchdog must be validated
  separately with spending approval. No rentals were attempted here.
- GPU image runtime, drivers, weights, vLLM authentication/flags, SSH tunnel and
  a real 50-task benchmark remain untested/unapproved.
- Parent's independent spec/security reviews remain required before broader use.
