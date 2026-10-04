"""No-spend tests for the exact-ID delete adapter; HTTP and credential loader are mocked."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def adapter():
    return importlib.import_module("vast_delete")


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"success": True}, True),
        ({"success": False}, False),
        ({}, False),
        (None, False),
        ([], False),
        ({"success": 1}, False),
        ({"success": "true"}, False),
    ],
)
def test_raw_http_delete_requires_literal_positive_ack(monkeypatch, payload, expected):
    m = adapter()
    response = Mock(status_code=200)
    response.json.return_value = payload
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.delete.return_value = response
    monkeypatch.setattr(m.requests, "Session", lambda: session)
    monkeypatch.setenv("VAST_API_KEY", "MOCK_NOT_A_SECRET")
    monkeypatch.setenv("VAST_URL", "https://invalid.example")
    assert m.delete_ack(789) == {"success": expected}
    assert session.trust_env is False
    session.delete.assert_called_once_with(
        "https://console.vast.ai/api/v0/instances/789/",
        headers={"Authorization": "Bearer MOCK_NOT_A_SECRET"},
        json={},
        timeout=30,
        allow_redirects=False,
    )


@pytest.mark.parametrize("instance", [True, 0, -1, "789", "789 --url evil", [789]])
def test_delete_rejects_invalid_id_before_any_io(instance, monkeypatch):
    m = adapter()
    monkeypatch.setattr(m.requests, "Session", lambda: pytest.fail("HTTP forbidden"))
    monkeypatch.setattr(
        m.subprocess, "run", lambda *a, **k: pytest.fail("credential access forbidden")
    )
    with pytest.raises(ValueError):
        m.delete_ack(instance)
    with pytest.raises(ValueError):
        m.destroy(instance)


@pytest.mark.parametrize("mode", ["rejected", "ambiguous", "lost-response", "stale-inventory"])
def test_mock_http_physical_state_stays_watched_until_ack_and_absence(monkeypatch, tmp_path, mode):
    m = adapter()
    life = importlib.import_module("real_lifecycle")
    from test_real_lifecycle import ChangingInventory, lease, row

    r = lease()
    r.update(instance=789, start_date=1010.0, status="running")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    path = root / (r["label"] + ".json")
    life.store(path, r)
    calls = []

    class Provider(ChangingInventory):
        def call(self, command, *args):
            if command == "destroy":
                return life.Vast().call(command, *args)
            return super().call(command, *args)

    p = Provider([row(r)], [3] if mode != "stale-inventory" else ())
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)

    def http_delete(url, **kwargs):
        assert url.endswith("/instances/789/")
        calls.append(url)
        response = Mock(status_code=200)
        if len(calls) == 1:
            if mode == "lost-response":
                raise m.requests.Timeout("mock secret-bearing error")
            response.json.return_value = {"success": False} if mode == "rejected" else {}
            if mode == "ambiguous":
                response.json.side_effect = ValueError("mock malformed JSON")
            if mode == "stale-inventory":
                response.json.return_value = {"success": True}
            return response
        p.rows = []  # Only positively acknowledged retry physically removes the resource.
        response.json.return_value = {"success": True}
        return response

    session.delete.side_effect = http_delete
    monkeypatch.setattr(m.requests, "Session", lambda: session)
    monkeypatch.setenv("VAST_API_KEY", "MOCK_NOT_A_SECRET")

    def helper(cmd, **kwargs):
        ack = m.delete_ack(789)
        return subprocess.CompletedProcess(cmd, 0 if ack["success"] else 1, json.dumps(ack), "")

    monkeypatch.setattr(m.subprocess, "run", helper)
    assert (
        life.pass_once(root=root, provider=p, execute=True, now=6500)["results"][0]["status"]
        == "retry"
    )
    assert life.read(path)["status"] == "cleanup" and len(p.rows) == 1
    p.omitted_calls = ()
    assert (
        life.pass_once(root=root, provider=p, execute=True, now=6501)["results"][0]["status"]
        == "absent"
    )
    assert life.read(path)["status"] == "destroyed" and len(p.rows) == 0
    assert len(calls) == 2


@pytest.mark.parametrize("status", [302, 400, 401, 404, 429, 500])
def test_http_status_never_becomes_success_even_with_positive_body(monkeypatch, status):
    m = adapter()
    response = Mock(status_code=status)
    response.json.return_value = {"success": True}
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.delete.return_value = response
    monkeypatch.setattr(m.requests, "Session", lambda: session)
    monkeypatch.setenv("VAST_API_KEY", "MOCK_NOT_A_SECRET")
    assert m.delete_ack(789) == {"success": False}
    response.json.assert_not_called()


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"success": 1}, {"success": "true"}, {"success": True, "extra": 1}]
)
def test_helper_output_schema_is_fail_closed(monkeypatch, payload):
    m = adapter()
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps(payload), ""),
    )
    with pytest.raises(RuntimeError, match="acknowledgement"):
        m.destroy(789)


@pytest.mark.parametrize("success", [True, False])
def test_helper_main_emits_only_boolean_ack(monkeypatch, capsys, success):
    m = adapter()
    monkeypatch.setattr(sys, "argv", ["vast_delete.py", "789"])
    monkeypatch.setattr(m, "delete_ack", lambda instance: {"success": success})
    assert m.main() == (0 if success else 1)
    output = capsys.readouterr()
    assert json.loads(output.out) == {"success": success} and not output.err


def test_trusted_vast_destroy_uses_credential_wrapper_functions_not_lossy_cli(monkeypatch):
    m = adapter()
    lifecycle = importlib.import_module("real_lifecycle")
    monkeypatch.setenv("VAST_API_KEY", "INHERITED_SECRET")
    monkeypatch.setenv("VAST_URL", "https://invalid.example")

    def fake(cmd, **kwargs):
        assert cmd == ["/usr/bin/bash", "-s"]
        assert set(kwargs["env"]) == {"PATH", "HOME", "BITWARDENCLI_APPDATA_DIR"}
        assert kwargs["env"]["BITWARDENCLI_APPDATA_DIR"] != "/opt/data/.config/Bitwarden-CLI-Hermes"
        script = kwargs["input"]
        assert "load_api_key() {" in script
        assert "main() {" not in script
        assert "unset VAST_API_KEY VAST_URL" in script
        assert "load_api_key\n" in script
        assert "exec /usr/bin/python3 -I " in script
        assert "vast_delete.py 789" in script
        assert "INHERITED_SECRET" not in script
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"success": True}), "")

    monkeypatch.setattr(m.subprocess, "run", fake)
    assert lifecycle.Vast().call("destroy", 789) == {"success": True}
