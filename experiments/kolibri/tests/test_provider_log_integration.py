"""Fake-only final log capture; GPU cleanup remains separate."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_final_provider_capture_redacts_original_payload_and_preserves_failure(
    monkeypatch, tmp_path
):
    m = importlib.import_module("real_controller")
    from test_real_lifecycle import lease

    r = lease()
    r.update(instance=789, start_date=1010.0)
    (tmp_path / "server.crt").write_text("CERT")
    (tmp_path / "server.key").write_text("KEY")
    seen = []

    def capture(record, directory, known_secrets, **kwargs):
        seen.extend(known_secrets)
        raise RuntimeError("provider logs unavailable")

    monkeypatch.setattr(m, "capture_provider_logs", capture)
    assert m.finish_provider_logs(r, tmp_path, {"api_key": "DISPOSABLE"}, object()) is False
    assert "KEY" in seen and "DISPOSABLE" in seen
    import base64
    import json

    assert (
        base64.b64encode(
            json.dumps({"api_key": "DISPOSABLE", "cert": "CERT", "key": "KEY"}).encode()
        ).decode()
        in seen
    )
    assert (tmp_path / "provider-log-failure.json").exists()
    assert (tmp_path / "provider-log-failure-traceback.txt").exists()


def test_final_export_rejects_empty_evidence_inventory(tmp_path):
    import pytest

    m = importlib.import_module("real_controller")
    from test_real_lifecycle import lease

    class Empty:
        def call(self, *args, **kwargs):
            return "{}"

    with pytest.raises(ValueError, match="missing required"):
        m.collect(Empty(), lease(), "pod", tmp_path, final=True)
