"""Exact TCP reachability controls; failures alone are never isolation proof."""

import errno
import socket


def tcp_probe(targets):
    results = []
    for name, host, port in targets:
        result = {"name": name, "host": host, "port": port, "connected": False}
        try:
            with socket.create_connection((host, port), timeout=2):
                result["connected"] = True
        except OSError as error:
            result.update(exception=type(error).__name__, errno=error.errno)
            result["denial_candidate"] = not isinstance(error, socket.gaierror) and (
                isinstance(error, TimeoutError)
                or error.errno in {errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EACCES, errno.EPERM}
            )
        results.append(result)
    return results


def require_denied(targets, negative, positive):
    require_controls(targets, positive)
    expected = [tuple(t) for t in targets]
    actual = [(p["name"], p["host"], p["port"]) for p in negative]
    if actual != expected or not all(
        p["connected"] is False and p.get("denial_candidate") is True for p in negative
    ):
        raise RuntimeError("missing exact-target denial evidence or probe unavailable")


def require_controls(targets, positive):
    expected = [tuple(t) for t in targets]
    actual = [(p["name"], p["host"], p["port"]) for p in positive]
    if actual != expected or not all(p["connected"] is True for p in positive):
        raise RuntimeError("missing or unavailable exact-target positive control")
