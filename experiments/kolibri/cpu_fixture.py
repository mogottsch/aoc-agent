"""Real AoC agent + Jupyter path, explicitly synthetic deterministic responses.

No Kolibri model, model weights, HTTP inference, or benchmark score claims.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

LABEL = "SYNTHETIC_CPU_FIXTURE_NOT_KOLIBRI"


async def run_fixture(fixture, denied_targets, positive_controls=()):
    from cpu_probe import require_controls, require_denied

    require_controls(denied_targets, positive_controls)
    import logfire
    import pydantic_ai.models
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    from aoc_agent.adapters.aoc.service import get_aoc_data_service
    from aoc_agent.adapters.storage.data_store import get_data_store
    from aoc_agent.benchmark.results import load_results
    from aoc_agent.core.settings import get_settings
    from run import run_day

    logfire.configure(send_to_logfire=False, console=False)
    for cache in (get_settings, get_data_store, get_aoc_data_service):
        cache.cache_clear()
    folder = Path("cache/2022")
    folder.mkdir(parents=True, exist_ok=True)
    article = '<article class="day-desc">SYNTHETIC: sum and count input integers.</article>'
    (folder / "day_1.unsolved.html").write_text(article)
    (folder / "day_1.input.txt").write_text(fixture["input"])
    answer1 = f"<p>Your puzzle answer was <code>{fixture['part1']}</code></p>"
    answer2 = f"<p>Your puzzle answer was <code>{fixture['part2']}</code></p>"
    (folder / "day_1.part1_solved.html").write_text(article + answer1)
    (folder / "day_1.part2_solved.html").write_text(article + answer1 + article + answer2)
    seen = []
    code = (
        Path(__file__).with_name("cpu_probe.py").read_text()
        + "\n"
        + """import json, pathlib, os
values = [int(v) for v in input_content.split()]
probes = tcp_probe(TARGETS)
require_denied(TARGETS, probes, CONTROLS)
print(json.dumps({"part1": sum(values), "part2": len(values), "token_present": pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists(), "uid": os.getuid(), "denied_targets": probes}))
""".replace("TARGETS", repr(denied_targets)).replace("CONTROLS", repr(positive_controls))
    )

    def response(messages, info):
        if not seen:
            seen.append("execute")
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "execute_python", {"code": code, "timeout_seconds": 20}, "fixture-execute"
                    )
                ]
            )
        returns = [
            p
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart) and p.tool_name == "execute_python"
        ]
        payload = returns[-1].content
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert not payload["error"], payload["error"]
        execution = json.loads(payload["output"])
        assert execution["part1"] == fixture["part1"] and execution["part2"] == fixture["part2"]
        assert not execution["token_present"]
        require_denied(denied_targets, execution["denied_targets"], positive_controls)
        seen.append(execution)
        tool = next(t for t in info.output_tools if "SolutionOutput" in t.name)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool.name,
                    {"part1": execution["part1"], "part2": execution["part2"]},
                    "fixture-final",
                )
            ]
        )

    previous_allow_requests = pydantic_ai.models.ALLOW_MODEL_REQUESTS
    pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
    try:
        path = Path("out/results.jsonl")
        await run_day(FunctionModel(response, model_name=LABEL), 2022, 1, path, model_id=LABEL)
        rows = list(load_results(path).values())
        assert len(rows) == 1 and rows[0].error is None
        assert rows[0].part1_correct and rows[0].part2_correct
        return {
            "model": LABEL,
            "inference": False,
            "jupyter": seen[-1],
            "part1_correct": rows[0].part1_correct,
            "part2_correct": rows[0].part2_correct,
        }
    finally:
        pydantic_ai.models.ALLOW_MODEL_REQUESTS = previous_allow_requests
        for cache in (get_settings, get_data_store, get_aoc_data_service):
            cache.cache_clear()


def finish_report(report, row, *, crash=False):
    print(json.dumps(report), flush=True)
    print("RESULT_JSONL " + row, flush=True)
    if crash:
        print(json.dumps({"actual_agent_runner_crash": True, "time": time.time()}), flush=True)
        os._exit(42)


def main():
    # Dependency init has public PyPI access; orchestration revokes it, verifies
    # policy read-back and negative socket probes, then releases this gate.
    end = time.monotonic() + 300
    while not Path("/work/released").exists():
        if time.monotonic() >= end:
            raise SystemExit("runtime isolation gate not released")
        time.sleep(1)
    opener = build_opener(ProxyHandler({}))
    with opener.open("http://fake-provider:8080/fixture", timeout=3) as response:
        fixture = json.loads(response.read())
    assert fixture["label"] == LABEL
    targets = json.loads(os.environ["DENIED_TARGETS"])
    controls = json.loads(Path("/work/positive-controls.json").read_text())
    report = asyncio.run(run_fixture(fixture, targets, controls))
    assert report["jupyter"]["uid"] == 10001
    report["fixture_http_allowed"] = True
    finish_report(
        report,
        Path("out/results.jsonl").read_text().strip(),
        crash=os.environ.get("CRASH_AFTER_FIXTURE") == "1",
    )


if __name__ == "__main__":
    main()
