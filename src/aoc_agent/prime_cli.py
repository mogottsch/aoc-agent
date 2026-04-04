from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict

import yaml
from pydantic import BaseModel
from verifiers import Environment
from verifiers.types import ClientConfig
from verifiers.utils.env_utils import load_environment


class PrimeCommandMode(StrEnum):
    EVAL = "eval"
    ROLLOUT = "rollout"


class PrimeToolChoiceMode(StrEnum):
    REQUIRED = "required"
    AUTO = "auto"


class PrimeSamplingArgs(TypedDict, total=False):
    max_tokens: int
    tool_choice: Literal["required"]


class PrimeBaseConfig(BaseModel):
    model: str
    dataset_path: Path | None = None
    max_concurrent: int = 4
    max_tokens: int = 768
    tool_choice: PrimeToolChoiceMode = PrimeToolChoiceMode.REQUIRED


class PrimeEvalConfig(PrimeBaseConfig):
    mode: Literal[PrimeCommandMode.EVAL] = PrimeCommandMode.EVAL
    output: Path = Path("results/prime-eval.jsonl")
    num_examples: int = 16
    rollouts_per_example: int = 1


class PrimeRolloutConfig(PrimeBaseConfig):
    mode: Literal[PrimeCommandMode.ROLLOUT] = PrimeCommandMode.ROLLOUT
    output: Path = Path("results/prime-rollout.jsonl")
    num_examples: int | None = None


type PrimeConfig = PrimeEvalConfig | PrimeRolloutConfig


def load_prime_config(path: Path) -> PrimeConfig:
    with path.open() as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise TypeError("Prime config must be a YAML mapping")

    mode = data.get("mode")
    if mode == PrimeCommandMode.EVAL.value:
        return PrimeEvalConfig.model_validate(data)
    if mode == PrimeCommandMode.ROLLOUT.value:
        return PrimeRolloutConfig.model_validate(data)
    raise ValueError("Prime config must set mode to 'eval' or 'rollout'")


def load_prime_eval_config(path: Path) -> PrimeEvalConfig:
    config = load_prime_config(path)
    if not isinstance(config, PrimeEvalConfig):
        message = f"Prime config at {path} must have mode: eval"
        raise TypeError(message)
    return config


def load_prime_rollout_config(path: Path) -> PrimeRolloutConfig:
    config = load_prime_config(path)
    if not isinstance(config, PrimeRolloutConfig):
        message = f"Prime config at {path} must have mode: rollout"
        raise TypeError(message)
    return config


def load_prime_environment(dataset_path: Path | None = None) -> Environment:
    if dataset_path is None:
        return load_environment("aoc-prime-env")
    return load_environment("aoc-prime-env", dataset_path=str(dataset_path))


def make_prime_client_config() -> ClientConfig:
    return ClientConfig(api_key_var="PRIME_API_KEY")


def build_prime_sampling_args(
    *, max_tokens: int, tool_choice: PrimeToolChoiceMode
) -> PrimeSamplingArgs:
    sampling_args: PrimeSamplingArgs = {"max_tokens": max_tokens}
    if tool_choice is PrimeToolChoiceMode.REQUIRED:
        sampling_args["tool_choice"] = PrimeToolChoiceMode.REQUIRED.value
    return sampling_args
