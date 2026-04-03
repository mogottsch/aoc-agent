from aoc_rl.config import RewardConfig
from aoc_rl.rewards import submission_reward, timeout_penalty, tool_penalty


def test_tool_penalty_respects_free_calls() -> None:
    config = RewardConfig(tool_call_penalty=-0.2, free_tool_calls=2)

    assert tool_penalty(1, config) == 0.0
    assert tool_penalty(2, config) == 0.0
    assert tool_penalty(3, config) == -0.2


def test_submission_reward_uses_part_specific_reward() -> None:
    config = RewardConfig(part1_correct=1.5, part2_correct=3.0, invalid_submission_penalty=-0.7)

    assert submission_reward(1, correct=True, config=config) == 1.5
    assert submission_reward(2, correct=True, config=config) == 3.0
    assert submission_reward(2, correct=False, config=config) == -0.7


def test_timeout_penalty_returns_configured_penalty() -> None:
    config = RewardConfig(python_timeout_penalty=-0.4)

    assert timeout_penalty(config) == -0.4
