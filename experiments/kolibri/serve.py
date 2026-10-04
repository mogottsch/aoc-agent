"""Print an authenticated serving plan. Does not pull images or start inference."""

import argparse
import json
import os
import subprocess
from pathlib import Path

MIN_KEY_LENGTH = 32


def serving_plan() -> dict:
    pins = json.loads(Path(__file__).with_name("pins.json").read_text())
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        "kolibri-aoc",
        "--gpus",
        "all",
        "--ipc=host",
        "--publish",
        "127.0.0.1:8000:8000",
        "--env",
        "VLLM_API_KEY",
        "--env",
        "VLLM_NO_USAGE_STATS=1",
        "--volume",
        "kolibri-hf-cache:/root/.cache/huggingface",
        pins["image_repository"] + "@" + pins["image_digest"],
        pins["model"],
        "--revision",
        pins["model_revision"],
        "--tokenizer-revision",
        pins["model_revision"],
        "--served-model-name",
        pins["model"],
        "--host",
        "0.0.0.0",  # noqa: S104 - container only; host publish is loopback
        "--port",
        "8000",
        "--tensor-parallel-size",
        "1",
        "--max-model-len",
        "32768",
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
    ]
    return {"execution": False, "command": command}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="explicitly permit image/weight download and GPU serving",
    )
    args = parser.parse_args()
    from verify_pins import validate_pins

    validate_pins(json.loads(Path(__file__).with_name("pins.json").read_text()))
    plan = serving_plan()
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return 0
    if len(os.environ.get("VLLM_API_KEY", "")) < MIN_KEY_LENGTH:
        parser.error(
            "set a dedicated high-entropy VLLM_API_KEY (at least 32 characters); nothing started"
        )
    # Never forward AoC, provider, HF or marketplace credentials into the image.
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "VLLM_API_KEY"}}
    try:
        return subprocess.run(plan["command"], env=env, check=False).returncode  # noqa: S603 - validated fixed plan
    except OSError:
        parser.exit(2, "Docker unavailable; nothing started.\n")


if __name__ == "__main__":
    raise SystemExit(main())
