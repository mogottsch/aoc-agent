from pathlib import Path

from verifiers.types import ClientConfig

from aoc_rl.prime.env import AocPrimeToolEnv, load_environment


def load_prime_environment(cache_dir: Path, year: int | None = None) -> AocPrimeToolEnv:
    return load_environment(cache_dir=cache_dir, year=year)


def make_prime_client_config() -> ClientConfig:
    return ClientConfig(api_key_var="PRIME_API_KEY")
