from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.core.models import SolutionError, SolutionOutput, SolverResult
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.sleep import sleep
from aoc_agent.tools.submit import submit_answer


def create_openai_model(
    model_name: str,
    base_url: str,
    api_key: str,
    *,
    disable_tool_choice: bool = False,
    openrouter_provider: str | None = None,
) -> Model:
    if openrouter_provider is not None:
        provider = OpenRouterProvider(api_key=api_key)
        settings = OpenRouterModelSettings(
            openrouter_provider={"only": [openrouter_provider], "allow_fallbacks": False}
        )
        profile = None
        if disable_tool_choice:
            profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
        return OpenRouterModel(model_name, provider=provider, profile=profile, settings=settings)

    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    profile = None
    if disable_tool_choice:
        profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
    return OpenAIChatModel(model_name, provider=provider, profile=profile)


def create_agent(model: Model, *, allow_sleep: bool) -> Agent[ToolContext, SolverResult]:
    tools = [execute_python, get_aoc_problem_description, submit_answer]
    if allow_sleep:
        tools.append(sleep)
    return Agent[ToolContext, SolverResult](
        model,
        deps_type=ToolContext,
        output_type=[SolutionOutput, SolutionError],
        tools=tools,
    )
