from typing import Any

from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.core.constants import OutputMode
from aoc_agent.core.models import SolutionError, SolutionOutput, SolverResult
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.sleep import sleep
from aoc_agent.tools.submit import submit_answer


def create_openai_model(  # noqa: PLR0913
    model_name: str,
    base_url: str,
    api_key: str,
    *,
    disable_tool_choice: bool = False,
    openrouter_provider: str | None = None,
    provider_name: str | None = None,
) -> Model:
    is_openrouter = (
        provider_name == "openrouter" or base_url.rstrip("/") == "https://openrouter.ai/api/v1"
    )
    if is_openrouter:
        provider = OpenRouterProvider(api_key=api_key)
        settings: OpenRouterModelSettings = {"openrouter_usage": {"include": True}}
        if openrouter_provider is not None:
            settings["openrouter_provider"] = {
                "only": [openrouter_provider],
                "allow_fallbacks": False,
            }
        profile = None
        if disable_tool_choice:
            profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
        return OpenRouterModel(model_name, provider=provider, profile=profile, settings=settings)

    is_copilot = (
        provider_name == "copilot" or base_url.rstrip("/") == "https://api.githubcopilot.com"
    )
    if is_copilot:
        from aoc_agent.adapters.copilot.provider import CopilotProvider  # noqa: PLC0415

        copilot_provider = CopilotProvider(api_key=api_key)
        profile = None
        if disable_tool_choice:
            profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
        return OpenAIChatModel(model_name, provider=copilot_provider, profile=profile)

    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    profile = None
    if disable_tool_choice:
        profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
    return OpenAIChatModel(model_name, provider=provider, profile=profile)


def _build_output_type(output_mode: OutputMode) -> Any:  # noqa: ANN401
    types = [SolutionOutput, SolutionError]
    if output_mode == OutputMode.TOOL:
        return [ToolOutput(t) for t in types]
    if output_mode == OutputMode.NATIVE:
        return NativeOutput(types)
    return PromptedOutput(types)


def create_agent(
    model: Model,
    *,
    allow_sleep: bool,
    output_mode: OutputMode = OutputMode.TOOL,
) -> Agent[ToolContext, SolverResult]:
    tools = [execute_python, get_aoc_problem_description, submit_answer]
    if allow_sleep:
        tools.append(sleep)
    return Agent[ToolContext, SolverResult](
        model,
        deps_type=ToolContext,
        output_type=_build_output_type(output_mode),
        tools=tools,
    )
