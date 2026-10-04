"""CPU TCP-only probe regressions; no service requests or real cluster access."""

import errno
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cpu_probe as probe


def test_positive_control_must_match_exact_host_and_port():
    targets = [["api", "10.43.0.1", 443]]
    with pytest.raises(RuntimeError, match="positive control"):
        probe.require_controls(
            targets, [{"name": "api", "host": "10.43.0.1", "port": 6443, "connected": True}]
        )


@pytest.mark.parametrize(
    "error",
    [
        socket.gaierror("DNS unavailable"),
        OSError(errno.ENETUNREACH, "unreachable"),
        OSError(errno.EBADF, "bad fd"),
    ],
)
def test_unavailable_errors_cannot_be_denial_evidence(monkeypatch, error):
    targets = [["api", "10.43.0.1", 443]]
    positive = [{"name": "api", "host": "10.43.0.1", "port": 443, "connected": True}]

    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(socket, "create_connection", unavailable)
    negative = probe.tcp_probe(targets)
    with pytest.raises(RuntimeError, match="denial"):
        probe.require_denied(targets, negative, positive)


def test_fresh_connection_refusal_requires_same_target_positive_control():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        targets = [["local", "127.0.0.1", port]]
        listener.listen()
        positive = probe.tcp_probe(targets)
        assert positive[0]["connected"]
    negative = probe.tcp_probe(targets)
    probe.require_denied(targets, negative, positive)
    with pytest.raises(RuntimeError, match="positive control"):
        probe.require_denied(targets, negative, [])
    # This controlled offline listener closure is a validator test, not policy proof.
