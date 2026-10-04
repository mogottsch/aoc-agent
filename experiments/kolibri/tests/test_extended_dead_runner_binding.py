"""Offline original debug-hold binding after an explicit lease extension."""

import copy
import json
from decimal import Decimal

import pytest
from test_dead_runner_replacement import replacement_fixture


def extended_fixture(tmp_path):
    import real_extend

    controller, original, kube, _, _ = replacement_fixture(tmp_path)
    deadline = original["deadline"] + 7200
    audit = {
        "version": 1,
        "action": "extend-approved",
        "original": copy.deepcopy(original),
        "additional_seconds": 7200,
        "new_deadline": deadline,
        "approved_at": 2000,
        "credit": 25,
        "rate": 4.19,
        "quoted_remaining_cost": float(
            real_extend.future_cost(deadline, 2000, 4.19)
            + Decimal(str(original["download_ceiling"]))
        ),
        "watchdog": {"job_id": "offline", "schedule_seconds": 60, "verified_at": 2000},
    }
    record = dict(original, deadline=deadline, extension=audit)
    real_extend.validate_extension(record)
    return controller, record, kube


def test_validated_extension_accepts_original_hold_without_rewriting_evidence(tmp_path):
    controller, record, kube = extended_fixture(tmp_path)
    path = tmp_path / "debug-hold.json"
    path.chmod(0o400)
    before = path.read_bytes()
    assert controller.owned_dead_runner(kube, record, tmp_path)["pod_uid"] == "pod-uid"
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o400


@pytest.mark.parametrize(
    "fault",
    [
        "old-deadline",
        "hold-instance",
        "hold-start",
        "hold-label",
        "hold-namespace",
        "schema",
        "new-deadline",
        "original-instance",
        "approval",
        "quote",
        "no-extension",
    ],
)
def test_original_hold_mismatch_or_invalid_extension_never_bypasses_binding(tmp_path, fault):
    controller, record, kube = extended_fixture(tmp_path)
    path = tmp_path / "debug-hold.json"
    hold = json.loads(path.read_text())
    if fault == "old-deadline":
        hold["deadline"] -= 1
    elif fault.startswith("hold-"):
        field = {"hold-start": "start_date"}.get(fault, fault.removeprefix("hold-"))
        hold[field] = "foreign"
    elif fault == "schema":
        record["extension"] = {"original": record["extension"]["original"]}
    elif fault == "new-deadline":
        record["extension"]["new_deadline"] += 1
    elif fault == "original-instance":
        record["extension"]["original"]["instance"] += 1
    elif fault == "approval":
        record["extension"]["action"] = "forged"
    elif fault == "quote":
        record["extension"]["quoted_remaining_cost"] = 0
    elif fault == "no-extension":
        del record["extension"]
    path.write_text(json.dumps(hold))
    with pytest.raises(ValueError):
        controller.owned_dead_runner(kube, record, tmp_path)
