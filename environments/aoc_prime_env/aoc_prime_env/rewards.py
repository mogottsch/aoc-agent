from pydantic import BaseModel


class RewardConfig(BaseModel):
    part1_correct: float = 1.0
    part2_correct: float = 1.0
    tool_call_penalty: float = -0.02
    python_timeout_penalty: float = -0.05
    invalid_submission_penalty: float = -0.1
    free_tool_calls: int = 4


def tool_penalty(tool_calls: int, config: RewardConfig) -> float:
    if tool_calls <= config.free_tool_calls:
        return 0.0
    return config.tool_call_penalty


def submission_reward(part: int, *, correct: bool, config: RewardConfig) -> float:
    if not correct:
        return config.invalid_submission_penalty
    if part == 1:
        return config.part1_correct
    return config.part2_correct


def timeout_penalty(config: RewardConfig) -> float:
    return config.python_timeout_penalty
