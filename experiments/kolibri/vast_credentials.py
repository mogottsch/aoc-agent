"""Private per-call encrypted vault snapshots; no plaintext credentials on disk."""

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def credential_env(
    *,
    source=Path("/opt/data/.config/Bitwarden-CLI-Hermes/data.json"),
    scratch=Path("/opt/data/cache/scratch"),
):
    # Each unlock/sync mutates CLI state. Never share it with another caller.
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe encrypted vault state")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            data = handle.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("encrypted vault state exceeds bound")
    finally:
        if fd is not None:
            os.close(fd)
    with tempfile.TemporaryDirectory(prefix="kolibri-vault-", dir=scratch) as directory:
        target = Path(directory) / "data.json"
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(out, "wb") as handle:
            handle.write(data)
        yield {
            "PATH": os.environ["PATH"],
            "HOME": "/opt/data",
            "BITWARDENCLI_APPDATA_DIR": directory,
        }
