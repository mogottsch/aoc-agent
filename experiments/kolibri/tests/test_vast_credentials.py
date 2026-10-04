"""Regression for isolated encrypted password-manager state, no live vault calls."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_isolated_vault_copies_private_state_and_removes_it_on_failure(tmp_path):
    module = importlib.import_module("vast_credentials")
    source = tmp_path / "data.json"
    source.write_text("encrypted fake state")
    source.chmod(0o600)
    with pytest.raises(RuntimeError):
        with module.credential_env(source=source, scratch=tmp_path) as env:
            directory = Path(env["BITWARDENCLI_APPDATA_DIR"])
            assert directory != source.parent
            assert directory.stat().st_mode & 0o077 == 0
            copied = directory / "data.json"
            assert copied.read_bytes() == source.read_bytes()
            assert copied.stat().st_mode & 0o077 == 0
            assert set(env) == {"PATH", "HOME", "BITWARDENCLI_APPDATA_DIR"}
            assert "VAST_API_KEY" not in env and "BW_SESSION" not in env
            raise RuntimeError("operation failed")
    assert not directory.exists()
    assert source.exists()
