"""Fake-only explicit extension tests; no credentials, Kubernetes or rentals."""

import importlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import real_lifecycle as lifecycle
from test_real_lifecycle import Provider, lease, row


def setup(tmp_path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    record = lease()
    record.update(
        instance=789, start_date=1010.0, status="debug-retained", reserve=0, deadline=11800
    )
    path = root / (record["label"] + ".json")
    lifecycle.store(path, record)
    receipt = root / "watchdog.json"
    receipt.write_text(
        json.dumps({"job_id": "parent-verified", "schedule_seconds": 60, "verified_at": 2000})
    )
    receipt.chmod(0o600)
    return root, record, path, receipt, Provider([row(record)], credit=25)


def extend(tmp_path):
    root, record, path, receipt, provider = setup(tmp_path)
    module = importlib.import_module("real_extend")
    result = module.extend_approved(
        path,
        additional_seconds=7200,
        watchdog_receipt=receipt,
        root=root,
        provider=provider,
        now=2000,
    )
    return module, root, record, path, receipt, provider, result


def test_explicit_extension_commits_audited_five_hour_deadline(tmp_path):
    module, root, original, path, receipt, provider, result = extend(tmp_path)
    current = lifecycle.read(path)
    assert result["new_deadline"] == current["deadline"] == 19000
    assert result["old_deadline"] == 11800
    assert lifecycle.MAX_TTL_SECONDS == 10800
    assert {k: v for k, v in current.items() if k not in {"deadline", "extension"}} == {
        k: v for k, v in original.items() if k != "deadline"
    }
    audit = root / original["label"] / "extension-receipt.json"
    assert json.loads(audit.read_text()) == current["extension"]
    assert audit.stat().st_mode & 0o777 == 0o400
    assert provider.deleted == []
    assert lifecycle.watchdog(current, provider, now=11800, execute=True) == "not-due"
    assert lifecycle.watchdog(current, provider, now=19000, execute=True) == "absent"
    lifecycle.store(path, current)
    assert lifecycle.read(path)["status"] == "destroyed"


def test_slow_fresh_provider_checks_cannot_commit_after_original_expiry(tmp_path, monkeypatch):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    clock = [2000]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    original_call = provider.call

    def slow(command, *args):
        if command == "list":
            clock[0] = original["deadline"]
        return original_call(command, *args)

    provider.call = slow
    with pytest.raises(ValueError, match="expired|fresh"):
        module.extend_approved(
            path, additional_seconds=7200, watchdog_receipt=receipt, root=root, provider=provider
        )
    assert lifecycle.read(path) == original
    assert not (root / original["label"] / "extension-receipt.json").exists()


@pytest.mark.parametrize("seconds", [0, -1, 7201, True, 7200.0, None])
def test_invalid_extension_bound_never_calls_provider(tmp_path, seconds):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=seconds,
            watchdog_receipt=receipt,
            root=root,
            provider=object(),
            now=2000,
        )
    assert lifecycle.read(path) == original


@pytest.mark.parametrize("status", ["prepared", "cleanup", "absent", "destroyed"])
def test_inactive_leases_never_extend(tmp_path, status):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, _ = setup(tmp_path)
    original["status"] = status
    lifecycle.store(path, original)
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=object(),
            now=2000,
        )
    assert lifecycle.read(path) == original


@pytest.mark.parametrize("clock", [11800, 12000, 999, float("nan"), True])
def test_expired_invalid_clock_cannot_extend(tmp_path, clock):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=object(),
            now=clock,
        )
    assert lifecycle.read(path) == original


@pytest.mark.parametrize(
    "changes",
    [
        {"label": "foreign"},
        {"start_date": 1011},
        {"id": 790},
        {"dph_total": 4.26},
        {"dph_total": 0},
        {"dph_total": True},
        {"dph_total": float("nan")},
        {"dph_total": None},
    ],
)
def test_fresh_inventory_mismatch_or_invalid_rate_refused(tmp_path, changes):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    provider.rows = [row(original, **changes)]
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original
    assert provider.deleted == []


@pytest.mark.parametrize("inventory", ["missing", "duplicate", "extra"])
def test_missing_duplicate_extra_inventory_refused(tmp_path, inventory):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    provider.rows = (
        []
        if inventory == "missing"
        else [
            row(original),
            row(original, id=790, label="foreign" if inventory == "extra" else original["label"]),
        ]
    )
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original


@pytest.mark.parametrize("credit", [9, 0, -1, float("nan"), float("inf"), True])
def test_fresh_credit_covers_all_original_remaining_time_plus_extension(tmp_path, credit):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    provider.credit = credit  # 9 affords just the extra 2h, not the entire remaining term.
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original
    assert not (root / original["label"] / "extension-receipt.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": ""},
        {"job_id": 1},
        {"schedule_seconds": 61},
        {"schedule_seconds": True},
        {"verified_at": 1699},
        {"verified_at": 2001},
        {"verified_at": float("nan")},
        {"extra": True},
    ],
)
def test_watchdog_receipt_exact_schema_freshness_refused(tmp_path, changes):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, _ = setup(tmp_path)
    receipt.write_text(
        json.dumps({"job_id": "cron", "schedule_seconds": 60, "verified_at": 2000, **changes})
    )
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=object(),
            now=2000,
        )
    assert lifecycle.read(path) == original


def test_foreign_provider_identity_refused(tmp_path):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    original_call = provider.call
    provider.call = lambda command, *args: (
        {"id": 7} if command == "balance" else original_call(command, *args)
    )
    with pytest.raises(ValueError, match="identity"):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original


def test_unowned_lease_refused_without_provider(tmp_path):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, _ = setup(tmp_path)
    path.unlink()
    original.update(status="launching", instance=None, start_date=None)
    lifecycle.store(path, original)
    with pytest.raises(ValueError, match="owned"):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=object(),
            now=2000,
        )


def test_receipt_before_store_interruption_recovers_exact_deadline_once(tmp_path, monkeypatch):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    commit = module.commit
    monkeypatch.setattr(module, "commit", lambda *args: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    target = root / original["label"] / "extension-receipt.json"
    frozen = target.read_bytes()
    assert lifecycle.read(path) == original
    monkeypatch.setattr(module, "commit", commit)
    result = module.extend_approved(
        path,
        additional_seconds=7200,
        watchdog_receipt=receipt,
        root=root,
        provider=provider,
        now=2100,
    )
    assert result["new_deadline"] == 19000
    assert target.read_bytes() == frozen
    assert lifecycle.read(path)["extension"]["approved_at"] == 2000
    with pytest.raises(ValueError, match="already extended"):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=object(),
            now=2200,
        )
    assert lifecycle.read(path)["deadline"] == 19000


@pytest.mark.parametrize("change", ["rate", "seconds", "status", "expired", "credit"])
def test_interrupted_extension_revalidates_fresh_gates_and_original_binding(
    tmp_path, monkeypatch, change
):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    commit = module.commit
    monkeypatch.setattr(module, "commit", lambda *args: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    monkeypatch.setattr(module, "commit", commit)
    if change == "rate":
        provider.rows[0]["dph_total"] = 4.20
    elif change == "status":
        original["status"] = "cleanup"
        lifecycle.store(path, original)
    elif change == "credit":
        provider.credit = 9
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7000 if change == "seconds" else 7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=11800 if change == "expired" else 2100,
        )
    assert lifecycle.read(path) == original


@pytest.mark.parametrize(
    "changes",
    [
        {"additional_seconds": 7201},
        {"new_deadline": 19001},
        {"approved_at": 11800},
        {"credit": 0},
        {"rate": 4.26},
        {"quoted_remaining_cost": 0},
        {"action": "resume"},
        {"version": True},
        {"extra": 1},
    ],
)
def test_structured_extension_audit_rejects_crafted_fields(tmp_path, changes):
    module, root, original, path, receipt, provider, result = extend(tmp_path)
    current = lifecycle.read(path)
    current["extension"].update(changes)
    with pytest.raises(ValueError):
        lifecycle.validate(current)


@pytest.mark.parametrize(
    "field,value",
    [
        ("created", 1001),
        ("instance", 790),
        ("start_date", 1011),
        ("hourly_ceiling", 4.7),
        ("reserve", 1),
        ("namespace", "kolibri-real-" + "b" * 12),
        ("deadline", 19001),
    ],
)
def test_extended_original_identity_policy_deadline_frozen(tmp_path, field, value):
    module, root, original, path, receipt, provider, result = extend(tmp_path)
    current = lifecycle.read(path)
    with pytest.raises(ValueError):
        lifecycle.store(path, {**current, field: value})
    assert lifecycle.read(path) == current


def test_generic_store_cannot_install_extension_even_with_matching_receipt(tmp_path):
    module, root, original, path, receipt, provider, result = extend(tmp_path)
    current = lifecycle.read(path)
    path.unlink()
    with pytest.raises(ValueError, match="explicit"):
        lifecycle.store(path, current)
    lifecycle.store(path, original)
    with pytest.raises(ValueError, match="frozen"):
        lifecycle.store(path, current)
    assert lifecycle.read(path) == original


@pytest.mark.parametrize("unsafe", ["missing", "writable", "world-readable", "symlink", "mismatch"])
def test_read_requires_exact_private_immutable_receipt(tmp_path, unsafe):
    module, root, original, path, receipt, provider, result = extend(tmp_path)
    target = Path(result["receipt"])
    if unsafe == "missing":
        target.unlink()
    elif unsafe == "writable":
        target.chmod(0o600)
    elif unsafe == "world-readable":
        target.chmod(0o444)
    elif unsafe == "symlink":
        target.unlink()
        target.symlink_to(receipt)
    else:
        target.chmod(0o600)
        target.write_text("{}")
        target.chmod(0o400)
    with pytest.raises((ValueError, OSError)):
        lifecycle.read(path)


def test_legacy_long_deadline_not_authorized_by_extension_schema(tmp_path):
    root, original, path, receipt, provider = setup(tmp_path)
    with pytest.raises(ValueError, match="TTL"):
        lifecycle.validate({**original, "deadline": 19000})
    with pytest.raises(ValueError, match="schema"):
        lifecycle.validate({**original, "deadline": 19000, "extension": {}})


def test_cli_requires_explicit_approval_arguments_and_reports_commit(tmp_path, monkeypatch, capsys):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    with pytest.raises(SystemExit):
        module.main(["--additional-seconds", "7200", "--watchdog-receipt", str(receipt)])
    original_extend = module.extend_approved
    monkeypatch.setattr(
        module,
        "extend_approved",
        lambda path, **kwargs: original_extend(
            path, **kwargs, root=root, provider=provider, now=2000
        ),
    )
    capsys.readouterr()
    assert (
        module.main(
            [
                "--extend-approved",
                str(path),
                "--additional-seconds",
                "7200",
                "--watchdog-receipt",
                str(receipt),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["new_deadline"] == lifecycle.read(path)["deadline"] == 19000
    assert (
        module.main(
            [
                "--extend-approved",
                str(path),
                "--additional-seconds",
                "7200",
                "--watchdog-receipt",
                str(receipt),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["status"] == "extension-refused"


@pytest.mark.parametrize("payload", [[], None, True, "bad"])
def test_malformed_interrupted_receipt_is_cleanly_refused(tmp_path, payload):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    directory = root / original["label"]
    directory.mkdir(mode=0o700)
    target = directory / "extension-receipt.json"
    target.write_text(json.dumps(payload))
    target.chmod(0o400)
    with pytest.raises(ValueError):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original


@pytest.mark.parametrize("seconds", [1, 3600, 7200])
def test_additional_deadline_is_relative_to_original_not_current_clock(tmp_path, seconds):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    result = module.extend_approved(
        path,
        additional_seconds=seconds,
        watchdog_receipt=receipt,
        root=root,
        provider=provider,
        now=2000,
    )
    assert result["new_deadline"] == original["deadline"] + seconds


def test_download_allowance_blocks_extension_before_receipt_or_store(tmp_path):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    path.unlink()
    original["reserve"] = 2.5
    lifecycle.store(path, original)
    compute = module.future_cost(original["deadline"] + 3600, 2000, 4.19)
    provider.credit = float(compute) + original["reserve"] + original["download_ceiling"] / 2
    with pytest.raises(ValueError, match="credit"):
        module.extend_approved(
            path,
            additional_seconds=3600,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original
    assert not (root / original["label"] / "extension-receipt.json").exists()
    assert provider.deleted == []


@pytest.mark.parametrize("include_download_quote", [False, True])
def test_extension_audit_rejects_forged_budget_omitting_download(tmp_path, include_download_quote):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    compute = module.future_cost(original["deadline"] + 3600, 2000, 4.19)
    audit = {
        "version": 1,
        "action": "extend-approved",
        "original": original,
        "additional_seconds": 3600,
        "new_deadline": original["deadline"] + 3600,
        "approved_at": 2000,
        "credit": float(compute) + original["reserve"] + original["download_ceiling"] / 2,
        "rate": 4.19,
        "quoted_remaining_cost": float(
            compute + (Decimal(str(original["download_ceiling"])) if include_download_quote else 0)
        ),
        "watchdog": json.loads(receipt.read_text()),
    }
    with pytest.raises(ValueError, match="unaffordable|quote"):
        lifecycle.validate({**original, "deadline": audit["new_deadline"], "extension": audit})
    assert lifecycle.read(path) == original
    assert not (root / original["label"] / "extension-receipt.json").exists()


def test_sufficient_current_credit_includes_frozen_download_quote(tmp_path):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    path.unlink()
    original["reserve"] = 2.5
    lifecycle.store(path, original)
    provider.credit = 17
    result = module.extend_approved(
        path,
        additional_seconds=1800,
        watchdog_receipt=receipt,
        root=root,
        provider=provider,
        now=2000,
    )
    current = lifecycle.read(path)
    compute = module.future_cost(result["new_deadline"], 2000, 4.19)
    quote = compute + Decimal(str(original["download_ceiling"]))
    assert Decimal("13") < compute < Decimal("14")
    assert current["extension"]["quoted_remaining_cost"] == float(quote)
    assert quote + Decimal(str(original["reserve"])) < Decimal(str(provider.credit))
    assert json.loads(Path(result["receipt"]).read_text()) == current["extension"]
    lifecycle.validate(current)
    assert provider.deleted == []


def test_original_reserve_still_applies_to_extension_affordability(tmp_path):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    path.unlink()
    original["reserve"] = 2.5
    lifecycle.store(path, original)
    provider.credit = 20
    with pytest.raises(ValueError, match="credit"):
        module.extend_approved(
            path,
            additional_seconds=7200,
            watchdog_receipt=receipt,
            root=root,
            provider=provider,
            now=2000,
        )
    assert lifecycle.read(path) == original


def test_watchdog_receipt_must_remain_fresh_after_slow_inventory(tmp_path, monkeypatch):
    module = importlib.import_module("real_extend")
    root, original, path, receipt, provider = setup(tmp_path)
    clock = [2000]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    original_call = provider.call

    def slow(command, *args):
        if command == "list":
            clock[0] = 2301
        return original_call(command, *args)

    provider.call = slow
    with pytest.raises(ValueError, match="fresh"):
        module.extend_approved(
            path, additional_seconds=7200, watchdog_receipt=receipt, root=root, provider=provider
        )
    assert lifecycle.read(path) == original
