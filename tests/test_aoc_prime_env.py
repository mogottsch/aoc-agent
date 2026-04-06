import asyncio

from aoc_prime_env.aoc_prime_env import AocPrimeEnv
from datasets import Dataset


async def _finalize_without_setup() -> dict[str, object]:
    env = AocPrimeEnv(dataset=Dataset.from_list([]))
    state = {
        "info": {
            "year": 2024,
            "day": 1,
        },
        "vf_reward": 0.5,
    }
    await env.finalize_state(state)
    return state


def test_finalize_state_handles_missing_solve_status() -> None:
    state = asyncio.run(_finalize_without_setup())

    assert state["vf_reward"] == 0.5
    assert state["vf_metrics"] == {
        "total_reward": 0.5,
        "solved_part1": 0.0,
        "solved_part2": 0.0,
    }
