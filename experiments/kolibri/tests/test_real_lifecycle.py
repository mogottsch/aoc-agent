"""No-spend lifecycle tests; fake adapter never calls Vast."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def module():
    return importlib.import_module("real_lifecycle")


class Provider:
    def __init__(self, rows=(), credit=9.65, lingering=False):
        self.rows = list(rows)
        self.credit = credit
        self.deleted = []
        self.lingering = lingering

    def call(self, command, *args):
        if command == "balance":
            return {
                "id": 639482,
                "username": "moritz-hermes-bot",
                "is_team": True,
                "credit": self.credit,
            }
        if command == "list":
            return self.rows
        if command == "destroy":
            self.deleted.append(int(args[0]))
            if not self.lingering:
                self.rows = [r for r in self.rows if r["id"] != int(args[0])]
            return {"success": True}  # Provider acknowledgement, independent of inventory.
        raise AssertionError(command)


def lease():
    return {
        "version": 1,
        "label": "hermes-kolibri-" + "a" * 32,
        "created": 1000.0,
        "deadline": 6400.0,
        "reserve": 2.5,
        "hourly_ceiling": 4.25,
        "download_ceiling": 0.6,
        "instance": None,
        "start_date": None,
        "status": "launching",
        "offer": 123,
        "namespace": "kolibri-real-" + "a" * 12,
    }


def row(record, **changes):
    return {"id": 789, "label": record["label"], "start_date": 1010.0, "dph_total": 4.19, **changes}


def test_due_unbound_ambiguous_launch_reconciles_exact_label_and_deletes():
    m = module()
    record = lease()
    p = Provider([row(record)])
    assert m.watchdog(record, p, now=6500, execute=True) == "absent"
    assert record["instance"] == 789
    assert p.deleted == [789]


@pytest.mark.parametrize("change", [{"label": "foreign"}, {"start_date": 1011.0}])
def test_bound_foreign_incarnation_is_never_deleted(change):
    m = module()
    r = lease()
    r.update(instance=789, start_date=1010.0)
    p = Provider([row(r, **change)])
    assert m.watchdog(r, p, now=7000, execute=True) == "ownership-or-schema-error"
    assert not p.deleted


def test_duplicate_ambiguous_response_is_never_deleted():
    m = module()
    r = lease()
    p = Provider([row(r), row(r, id=790)])
    assert m.watchdog(r, p, now=7000, execute=True) == "ownership-or-schema-error"
    assert not p.deleted


def test_delete_ack_with_live_readback_retries():
    m = module()
    r = lease()
    p = Provider([row(r)], lingering=True)
    assert m.watchdog(r, p, now=7000, execute=True) == "retry"
    assert r["status"] == "cleanup"


@pytest.mark.parametrize("credit,rate", [(-0.01, 4.19), (2.4, 4.19), (9.65, 4.5), (9.65, None)])
def test_reserve_or_rate_violation_stops_before_ttl(credit, rate):
    m = module()
    r = lease()
    p = Provider([row(r, dph_total=rate)], credit=credit)
    assert m.watchdog(r, p, now=1100, execute=True) == "absent"
    assert p.deleted == [789]


def test_controller_lock_waits_for_short_watchdog_contention(tmp_path):
    import threading
    import time

    m = module()
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    held = m.locked(root)
    timer = threading.Timer(0.1, held.close)
    timer.start()
    try:
        start = time.monotonic()
        with m.locked(root):
            assert time.monotonic() - start >= 0.05
    finally:
        timer.join()
        held.close()


def test_explicit_zero_reserve_lease_is_valid_and_watchdog_still_checks_rate():
    m = module()
    r = lease()
    r["reserve"] = 0.0
    m.validate(r)
    p = Provider([row(r)], credit=0.1)
    assert m.watchdog(r, p, now=1100, execute=True) == "not-due"
    p.credit = 0
    assert m.watchdog(r, p, now=1100, execute=True) == "absent"


def test_empty_state_never_calls_provider(tmp_path):
    assert (
        module().pass_once(root=tmp_path / "missing", execute=True, provider=object())["leases"]
        == 0
    )


def test_no_matching_inventory_never_deletes():
    m = module()
    r = lease()
    p = Provider([row(r, label="other")])
    assert m.watchdog(r, p, now=7000, execute=True) == "awaiting-reconciliation"
    assert not p.deleted


def test_dry_watchdog_never_calls_provider():
    assert module().watchdog(lease(), object(), now=7000) == "dry-run"


def test_lease_private_durable_readback_and_symlink_rejection(tmp_path):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    path = root / "lease.json"
    m.store(path, lease())
    assert m.read(path) == lease()
    path.unlink()
    path.symlink_to(tmp_path / "foreign")
    with pytest.raises(ValueError):
        m.store(path, lease())


def test_serving_launch_is_direct_tls_not_nested_docker(tmp_path):
    m = module()
    r = lease()
    command = m.launch_command(r, {"api_key": "k" * 64, "cert": "CERT", "key": "KEY"})
    assert command[:2] == ["launch", "123"]
    assert "--entrypoint" in command and "--cancel-unavail" in command
    script = command[-1]
    assert "docker" not in script and "--ssl-certfile" in script
    import shlex

    pins = __import__("json").loads(Path(m.__file__).with_name("pins.json").read_text())
    assert command[command.index("--image") + 1] == (
        pins["image_repository"] + "@" + pins["image_digest"]
    )
    assert shlex.split(script.rsplit("exec ", 1)[1]) == [
        "vllm",
        "serve",
        pins["model"],
        "--revision",
        "e52eb4627d11516b0c01de49210ab5a4e4061444",
        "--tokenizer-revision",
        "e52eb4627d11516b0c01de49210ab5a4e4061444",
        "--served-model-name",
        pins["model"],
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--tensor-parallel-size",
        "1",
        "--max-model-len",
        "131072",
        "--max-num-seqs",
        "1",
        "--gpu-memory-utilization",
        "0.90",
        "--kv-cache-dtype",
        "fp8",
        "--reasoning-parser",
        "kolibri1",
        "--tool-call-parser",
        "kolibri1",
        "--enable-auto-tool-choice",
        "--generation-config",
        "vllm",
        "--ssl-certfile",
        "/tmp/kolibri.crt",
        "--ssl-keyfile",
        "/tmp/kolibri.key",
    ]
    assert "set -x" not in script


def test_late_ambiguous_create_after_absence_is_still_cleaned(tmp_path):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    r["status"] = "absent"
    path = root / (r["label"] + ".json")
    m.store(path, r)
    p = Provider([row(r)])
    report = m.pass_once(root=root, execute=True, provider=p, now=7000)
    assert report["results"][0]["status"] == "absent" and p.deleted == [789]


def test_atomic_write_survives_stale_temp_from_killed_writer(tmp_path):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    path = root / "lease.json"
    path.with_suffix(".new").write_text("interrupted")
    m.store(path, lease())
    assert m.read(path) == lease()


def test_vast_adapter_scrubs_all_inherited_credentials(monkeypatch):
    import subprocess

    m = module()
    observed = {}

    def fake(cmd, **kwargs):
        observed.update(kwargs)
        assert cmd == ["/usr/local/bin/vastctl", "list"]
        return subprocess.CompletedProcess(cmd, 0, "[]", "")

    monkeypatch.setenv("VAST_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("VAST_URL", "https://malicious.invalid")
    monkeypatch.setattr(m.subprocess, "run", fake)
    assert m.Vast().call("list") == []
    assert set(observed["env"]) == {"PATH", "HOME", "BITWARDENCLI_APPDATA_DIR"}
    assert observed["env"]["BITWARDENCLI_APPDATA_DIR"] != "/opt/data/.config/Bitwarden-CLI-Hermes"
    assert not Path(observed["env"]["BITWARDENCLI_APPDATA_DIR"]).exists()


class ChangingInventory(Provider):
    """Inventory omissions do not remove the underlying billable resource."""

    def __init__(self, rows, omitted_calls=()):
        super().__init__(rows)
        self.omitted_calls = omitted_calls
        self.list_calls = 0

    def call(self, command, *args):
        if command == "list":
            self.list_calls += 1
            if self.list_calls in self.omitted_calls:
                return []
        return super().call(command, *args)


@pytest.mark.parametrize("omitted,first_now", [([1], 1100), ([2], 6500)])
def test_bound_inventory_omission_remains_watchable_until_reappearing_resource_deleted(
    tmp_path, omitted, first_now
):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(instance=789, start_date=1010.0, status="running")
    path = root / (r["label"] + ".json")
    m.store(path, r)
    p = ChangingInventory([row(r)], omitted)
    m.pass_once(root=root, execute=True, provider=p, now=first_now)
    assert len(p.rows) == 1  # Still physically billable despite the empty inventory.
    assert m.read(path)["status"] not in {"absent", "destroyed"}
    report = m.pass_once(root=root, execute=True, provider=p, now=6501)
    assert report["results"][0]["status"] == "absent"
    assert len(p.rows) == 0 and p.deleted == [789]


def test_unbound_expiry_never_resolves_empty_inventory_and_cleans_late_resource(tmp_path):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    path = root / (r["label"] + ".json")
    m.store(path, r)
    p = ChangingInventory([row(r)], [1, 2, 3])
    for now in (6500, 7000, 8000):
        report = m.pass_once(root=root, execute=True, provider=p, now=now)
        assert report["results"][0]["status"] == "awaiting-reconciliation"
        assert m.read(path)["status"] not in {"absent", "destroyed"}
        assert len(p.rows) == 1 and not p.deleted
    report = m.pass_once(root=root, execute=True, provider=p, now=9000)
    assert report["results"][0]["status"] == "absent"
    assert len(p.rows) == 0 and p.deleted == [789]


def test_legacy_bound_absence_is_not_terminal_and_reappearing_resource_is_deleted(tmp_path):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(status="absent", instance=789, start_date=1010.0)
    path = root / (r["label"] + ".json")
    m.store(path, r)
    p = Provider([row(r)])
    report = m.pass_once(root=root, execute=True, provider=p, now=7000)
    assert report["results"][0]["status"] == "absent"
    assert len(p.rows) == 0 and p.deleted == [789]


class BalanceUnavailable(Provider):
    def __init__(self, rows):
        super().__init__(rows)
        self.balance_calls = 0

    def call(self, command, *args):
        if command == "balance":
            self.balance_calls += 1
            raise RuntimeError("balance unavailable")
        return super().call(command, *args)


@pytest.mark.parametrize(
    "now,finish,status",
    [(6400, False, "running"), (1100, True, "running"), (1100, False, "cleanup")],
)
def test_mandatory_cleanup_deletes_owned_resource_without_balance(now, finish, status):
    m = module()
    r = lease()
    r.update(instance=789, start_date=1010.0, status=status)
    p = BalanceUnavailable([row(r)])
    saved = []
    assert (
        m.watchdog(r, p, now=now, execute=True, finish=finish, save=lambda r: saved.append(dict(r)))
        == "absent"
    )
    assert p.deleted == [789] and len(p.rows) == 0
    assert p.balance_calls == 0
    assert saved[0]["status"] == "cleanup" and saved[-1]["status"] == "destroyed"


def test_normal_watchdog_balance_outage_does_not_authorize_continued_run():
    r = lease()
    p = BalanceUnavailable([row(r)])
    assert module().watchdog(r, p, now=1100, execute=True) == "retry"
    assert p.balance_calls == 1 and len(p.rows) == 1 and not p.deleted


def test_finish_missing_bound_inventory_persists_cleanup_before_balance():
    r = lease()
    r.update(instance=789, start_date=1010.0, status="running")
    p = BalanceUnavailable([])
    saved = []
    assert (
        module().watchdog(
            r, p, now=1100, execute=True, finish=True, save=lambda r: saved.append(dict(r))
        )
        == "awaiting-reconciliation"
    )
    assert saved[0]["status"] == "cleanup" and r["status"] == "cleanup"
    assert not p.deleted and p.balance_calls == 0


def test_watchdog_attachment_write_failure_preserves_durable_intent_for_next_pass(
    tmp_path, monkeypatch
):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    path = root / (r["label"] + ".json")
    m.store(path, r)
    original_store = m.store
    failed = False

    def fail_binding_once(path, record):
        nonlocal failed
        if record["instance"] is not None and not failed:
            failed = True
            raise OSError("injected attachment failure")
        original_store(path, record)

    monkeypatch.setattr(m, "store", fail_binding_once)
    p = BalanceUnavailable([row(r)])
    report = m.pass_once(root=root, execute=True, provider=p, now=7000)
    assert report["results"][0]["status"] == "retry"
    durable = m.read(path)
    assert durable["status"] == "cleanup" and durable["instance"] is None
    assert len(p.rows) == 1 and not p.deleted
    report = m.pass_once(root=root, execute=True, provider=p, now=7001)
    assert report["results"][0]["status"] == "absent"
    assert len(p.rows) == 0 and p.deleted == [789] and p.balance_calls == 0


@pytest.mark.parametrize("change", [{"label": "foreign"}, {"start_date": 1011.0}])
def test_mandatory_cleanup_balance_outage_still_rechecks_ownership_before_delete(change):
    r = lease()
    r.update(instance=789, start_date=1010.0, status="running")

    class ChangedOwner(BalanceUnavailable):
        list_calls = 0

        def call(self, command, *args):
            if command == "list":
                self.list_calls += 1
                if self.list_calls == 2:
                    self.rows = [row(r, **change)]
            return super().call(command, *args)

    p = ChangedOwner([row(r)])
    assert module().watchdog(r, p, now=6400, execute=True) == "ownership-or-schema-error"
    assert len(p.rows) == 1 and not p.deleted and p.balance_calls == 0


@pytest.mark.parametrize(
    "ack", [None, {}, {"success": False}, {"success": 1}, {"success": "true"}, {"destroyed": True}]
)
def test_unacknowledged_delete_with_inventory_omission_remains_cleanup_and_retries(tmp_path, ack):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(instance=789, start_date=1010.0, status="running")
    path = root / (r["label"] + ".json")
    m.store(path, r)

    class DeclinedDelete(ChangingInventory):
        def call(self, command, *args):
            if command == "destroy" and not self.deleted:
                self.deleted.append(args[0])
                return ack  # Physical resource survives; readback would temporarily omit it.
            return super().call(command, *args)

    p = DeclinedDelete([row(r)], [3])
    report = m.pass_once(root=root, execute=True, provider=p, now=6500)
    assert report["results"][0]["status"] == "retry"
    assert m.read(path)["status"] == "cleanup"  # Same durable state blocks singleton admission.
    assert len(p.rows) == 1 and p.deleted == [789]
    p.omitted_calls = ()
    report = m.pass_once(root=root, execute=True, provider=p, now=6501)
    assert report["results"][0]["status"] == "absent"
    assert m.read(path)["status"] == "destroyed"
    assert len(p.rows) == 0 and p.deleted == [789, 789]


def test_verified_destroy_is_the_only_terminal_cleanup_state(tmp_path):
    m = module()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    r = lease()
    path = root / (r["label"] + ".json")
    p = Provider([row(r)])
    assert m.watchdog(r, p, now=6400, execute=True, save=lambda r: m.store(path, r)) == "absent"
    assert m.read(path)["status"] == "destroyed" and p.deleted == [789]
    assert (
        m.pass_once(root=root, execute=True, provider=object(), now=6401)["results"][0]["status"]
        == "absent"
    )
    r.update(instance=None, start_date=None)
    with pytest.raises(ValueError, match="verified binding"):
        m.validate(r)


@pytest.mark.parametrize(
    "now,credit,rate,finish,expected",
    [
        (1100, 9.65, 4.19, False, "not-due"),
        (6400, 9.65, 4.19, False, "absent"),
        (1100, 0, 4.19, False, "absent"),
        (1100, 9.65, 4.5, False, "absent"),
        (1100, 9.65, 4.19, True, "absent"),
    ],
)
def test_retained_failure_is_bounded_by_original_watchdog(now, credit, rate, finish, expected):
    r = lease()
    r.update(instance=789, start_date=1010.0, status="debug-retained")
    binding = (r["instance"], r["start_date"], r["deadline"])
    p = Provider([row(r, dph_total=rate)], credit=credit)
    assert module().watchdog(r, p, now=now, execute=True, finish=finish) == expected
    assert (r["instance"], r["start_date"], r["deadline"]) == binding
    assert p.deleted == ([] if expected == "not-due" else [789])


def test_debug_retention_requires_verified_binding():
    r = lease()
    r["status"] = "debug-retained"
    with pytest.raises(ValueError, match="verified binding"):
        module().validate(r)


@pytest.mark.parametrize("boundary", ["expiry", "credit", "rate"])
@pytest.mark.parametrize("hold_written", [False, True])
def test_independent_watchdog_cleans_retained_namespace_after_gpu_without_controller(
    monkeypatch, tmp_path, boundary, hold_written
):
    m = module()
    controller = importlib.import_module("real_controller")
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(instance=789, start_date=1010.0, status="debug-retained")
    path = root / (r["label"] + ".json")
    m.store(path, r)
    directory = root / r["label"]
    directory.mkdir(mode=0o700)
    (directory / "namespace-attempted").write_text(r["namespace"])
    if hold_written:
        (directory / "debug-hold.json").write_text("{}")
    p = Provider(
        [row(r, dph_total=4.5 if boundary == "rate" else 4.19)],
        credit=0 if boundary == "credit" else 9.65,
    )
    calls = []

    def finish(kube, record, pod, artifacts):
        assert p.deleted == [789]  # Namespace/evidence failure must not delay GPU billing stop.
        with m.locked(root, timeout=0):
            pass  # Slow Kubernetes work never monopolizes the billing watchdog lock.
        calls.append(record["namespace"])
        return False  # Retry evidence export; never force namespace deletion.

    monkeypatch.setattr(controller, "finish_namespace", finish)
    m.pass_once(
        root=root,
        provider=p,
        kube=object(),
        execute=True,
        now=6400 if boundary == "expiry" else 1100,
    )
    assert calls == [r["namespace"]]
    assert m.read(path)["status"] == "destroyed"
    m.pass_once(root=root, provider=p, kube=object(), execute=True, now=6401)
    assert calls == [r["namespace"], r["namespace"]]


@pytest.mark.parametrize(
    "change",
    [
        {"deadline": 6401.0, "created": 1001.0},
        {"instance": 790},
        {"start_date": 1011.0},
        {"namespace": "kolibri-real-" + "b" * 12},
    ],
)
def test_retained_identity_and_original_deadline_cannot_be_rewritten(tmp_path, change):
    m = module()
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(instance=789, start_date=1010.0, status="debug-retained")
    path = root / (r["label"] + ".json")
    m.store(path, r)
    with pytest.raises(ValueError, match="frozen"):
        m.store(path, {**r, **change})
    assert m.read(path) == r


@pytest.mark.parametrize("historical_count", [4, 6])
def test_terminal_history_does_not_block_expired_retained_billing_cleanup(
    tmp_path, historical_count
):
    m = module()
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    for i in range(historical_count):
        history = lease()
        history.update(
            label=f"hermes-kolibri-{i:032x}",
            status="destroyed",
            instance=i + 1,
            start_date=1010.0,
        )
        m.store(root / (history["label"] + ".json"), history)
    retained = lease()
    retained.update(instance=789, start_date=1010.0, status="debug-retained")
    path = root / (retained["label"] + ".json")
    m.store(path, retained)
    p = Provider([row(retained)])

    report = m.pass_once(root=root, execute=True, provider=p, now=6400)

    assert report["leases"] == historical_count + 1
    assert len(report["results"]) == historical_count + 1
    assert m.read(path)["status"] == "destroyed"
    assert p.deleted == [789] and not p.rows  # Adapter rejects any replacement launch.


@pytest.mark.parametrize("remaining_count", [0, 5])
def test_over_limit_unresolved_leases_service_all_cleanup_before_guard(
    monkeypatch, tmp_path, remaining_count
):
    m = module()
    controller = importlib.import_module("real_controller")
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    paths = []
    rows = []
    for i in range(6 + remaining_count):
        r = lease()
        r.update(label=f"hermes-kolibri-{i:032x}", namespace=f"kolibri-real-{i:012x}")
        if i < 6:
            r.update(
                status="debug-retained" if i % 2 == 0 else "cleanup",
                instance=i + 1,
                start_date=1010.0,
                deadline=1100.0,
            )
            rows.append(row(r, id=i + 1))
            directory = root / r["label"]
            directory.mkdir(mode=0o700)
            (directory / "namespace-attempted").write_text(r["namespace"])
        path = root / (r["label"] + ".json")
        m.store(path, r)
        paths.append(path)
    p = Provider(rows)
    namespaces = []

    def finish(kube, record, pod, directory):
        assert p.deleted == list(range(1, 7))  # All billing cleanup precedes evidence work.
        with m.locked(root, timeout=0):
            pass
        namespaces.append(record["namespace"])
        return True

    monkeypatch.setattr(controller, "finish_namespace", finish)
    if remaining_count:
        with pytest.raises(ValueError, match="too many leases"):
            m.pass_once(root=root, execute=True, provider=p, kube=object(), now=1100)
    else:
        report = m.pass_once(root=root, execute=True, provider=p, kube=object(), now=1100)
        assert report["leases"] == 6
    assert p.deleted == list(range(1, 7)) and not p.rows
    assert namespaces == [f"kolibri-real-{i:012x}" for i in range(6)]
    assert all(m.read(path)["status"] == "destroyed" for path in paths[:6])
    assert all(m.read(path)["status"] == "launching" for path in paths[6:])


def test_retained_rate_boundary_does_not_depend_on_balance_availability():
    r = lease()
    r.update(instance=789, start_date=1010.0, status="debug-retained")
    p = BalanceUnavailable([row(r, dph_total=4.5)])
    assert module().watchdog(r, p, now=1100, execute=True) == "absent"
    assert p.deleted == [789] and p.balance_calls == 0


@pytest.mark.parametrize("ttl", [5400, 10800])
def test_legacy_and_three_hour_leases_expire_at_original_boundary(tmp_path, ttl):
    m = module()
    r = lease()
    r["deadline"] = r["created"] + ttl
    m.validate(r)
    p = Provider([row(r)], credit=24.9192)
    assert m.watchdog(r, p, now=r["deadline"] - 0.001, execute=True) == "not-due"
    assert m.watchdog(r, p, now=r["deadline"], execute=True) == "absent"
    assert p.deleted == [789]
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    path = root / "lease.json"
    m.store(path, r)
    with pytest.raises(ValueError):
        m.store(path, {**r, "created": r["created"] + 1, "deadline": r["deadline"] + 1})
    assert m.read(path)["deadline"] == r["deadline"]


@pytest.mark.parametrize("ttl", [0, -1, 10800.001, 10801])
def test_lifetime_cannot_exceed_three_hours(ttl):
    r = lease()
    r["deadline"] = r["created"] + ttl
    with pytest.raises(ValueError, match="TTL"):
        module().validate(r)
