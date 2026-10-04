"""Verify public immutable OCI/HF metadata only, never layers or model weights."""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_METADATA_BYTES = 2_000_000


def validate_pins(pins: dict) -> None:
    for field in ("model_revision", "plugin_commit"):
        if re.fullmatch(r"[0-9a-f]{40}", pins[field]) is None:
            message = f"invalid immutable {field} revision"
            raise ValueError(message)
    for field in ("image_digest", "linux_amd64_digest", "image_config_digest"):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", pins[field]) is None:
            message = f"invalid immutable {field}"
            raise ValueError(message)
    if (
        pins["model"] != "Aleph-Alpha/Kolibri-1"
        or pins["image_repository"] != "ghcr.io/aleph-alpha/aleph-alpha-inference"
    ):
        raise ValueError("pins must reference official Kolibri artifacts only")


def fetch_metadata(url: str, headers: dict | None = None) -> bytes:
    if urlsplit(url).scheme != "https":
        raise ValueError("public metadata requires HTTPS")
    with urlopen(Request(url, headers=headers or {}), timeout=45) as response:  # noqa: S310 - HTTPS checked
        body = response.read(MAX_METADATA_BYTES + 1)
    if len(body) > MAX_METADATA_BYTES:
        raise ValueError("public metadata exceeded safe read limit")
    return body


def verify_public(pins: dict, *, fetch: Callable = fetch_metadata) -> dict:
    validate_pins(pins)
    repository = "aleph-alpha/aleph-alpha-inference"
    token = json.loads(
        fetch("https://ghcr.io/token?service=ghcr.io&scope=repository:" + repository + ":pull")
    )["token"]
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": (
            "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json"
        ),
    }
    registry = "https://ghcr.io/v2/" + repository

    def checked(url: str, digest: str, auth: dict | None = None) -> dict:
        body = fetch(url, auth)
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("public metadata digest mismatch")
        return json.loads(body)

    index = checked(registry + "/manifests/" + pins["image_digest"], pins["image_digest"], headers)
    checked(registry + "/manifests/" + pins["image_tag"], pins["image_digest"], headers)
    platforms = [
        m
        for m in index["manifests"]
        if m.get("platform") == {"os": "linux", "architecture": "amd64"}
    ]
    if len(platforms) != 1 or platforms[0]["digest"] != pins["linux_amd64_digest"]:
        raise ValueError("unexpected linux/amd64 image manifest")
    child = checked(
        registry + "/manifests/" + pins["linux_amd64_digest"], pins["linux_amd64_digest"], headers
    )
    if child["config"]["digest"] != pins["image_config_digest"]:
        raise ValueError("image config digest mismatch")
    image_config = checked(
        registry + "/blobs/" + pins["image_config_digest"], pins["image_config_digest"], headers
    )["config"]
    if (
        image_config["Entrypoint"] != ["vllm", "serve"]
        or image_config["Labels"]["org.opencontainers.image.version"] != pins["image_tag"]
        or "CUDA_VERSION=" + pins["cuda_version"] not in image_config["Env"]
    ):
        raise ValueError("unexpected image version, entrypoint or CUDA metadata")
    source = (
        "https://api.github.com/repos/Aleph-Alpha/aleph-alpha-inference/git/ref/tags/"
        + pins["plugin_release"]
    )
    if json.loads(fetch(source))["object"]["sha"] != pins["plugin_commit"]:
        raise ValueError("plugin release revision mismatch")
    hf = "https://huggingface.co/"
    model = json.loads(
        fetch(hf + "api/models/" + pins["model"] + "/revision/" + pins["model_revision"])
    )
    if model["sha"] != pins["model_revision"] or model.get("gated"):
        raise ValueError("model revision is not public or mismatches pin")
    base = hf + pins["model"] + "/resolve/" + pins["model_revision"] + "/"
    config = checked(base + "config.json", "sha256:" + pins["model_config_sha256"])
    generation = checked(
        base + "generation_config.json", "sha256:" + pins["generation_config_sha256"]
    )
    if (
        config["architectures"] != ["Kolibri1ForCausalLM"]
        or config["quantization_config"]["quant_method"] != "fp8"
    ):
        raise ValueError("model is not official Kolibri FP8")
    if any(
        generation[k] != v for k, v in {"temperature": 1.0, "top_p": 0.97, "top_k": 128}.items()
    ):
        raise ValueError("recommended sampling metadata changed")
    return {"verified": True, "scope": "public metadata only; no layers or weights", "pins": pins}


if __name__ == "__main__":
    try:
        print(
            json.dumps(
                verify_public(json.loads(Path(__file__).with_name("pins.json").read_text())),
                indent=2,
            )
        )
    except (ValueError, KeyError, OSError):
        raise SystemExit(
            "Public metadata verification failed; no runtime verification claimed."
        ) from None
