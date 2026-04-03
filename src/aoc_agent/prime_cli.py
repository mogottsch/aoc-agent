from pathlib import Path

from verifiers.types import ClientConfig

from aoc_rl.prime import load_environment


def load_prime_environment(cache_dir: Path, results_path: Path, year: int | None = None):
    return load_environment(cache_dir=cache_dir, results_path=results_path, year=year)


def make_prime_client_config() -> ClientConfig:
    return ClientConfig(api_key_var="PRIME_API_KEY")
