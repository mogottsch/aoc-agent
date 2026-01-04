from aoc_agent.core.constants import DAY_25


def build_agent_instructions(*, day: int, allow_sleep: bool) -> list[str]:
    tools = [
        "- execute_python: Run Python code",
        "- submit: Submit and verify your answer",
        "- get_aoc_problem_description: Get updated problem text",
    ]
    if allow_sleep:
        tools.append("- sleep: Wait for specified seconds (use when rate limited)")

    instructions = [
        "- The real puzzle input is already available in the variable `input_content`.",
        "- Variables and imports persist between `execute_python` calls.",
        "- Store large data in variables rather than printing everything.",
        "- The `execute_python` output is truncated to 2000 characters by default.",
        "- You can increase `max_output_length` if you need to see more.",
        "- Each `execute_python` call has a wall-clock timeout via `timeout_seconds` "
        "(default 30s).",
        "- The examples in the problem description are for understanding only, "
        "not the actual input.",
    ]

    if day == DAY_25:
        instructions.append("- Note: Day 25 has no submit-able Part 2 answer; solve Part 1 only.")
    else:
        instructions.extend(
            [
                "- You must solve both Part 1 and Part 2 before returning.",
                "- Use get_aoc_problem_description to see Part 2 after submitting Part 1.",
            ]
        )

    if allow_sleep:
        instructions.append(
            "- If rate limited, use the sleep tool with the suggested wait time, then retry."
        )

    tools_block = "\n".join(tools)
    instructions_block = "\n".join(instructions)
    return [f"Tools:\n{tools_block}\n\nInstructions:\n{instructions_block}"]


def build_agent_prompt(*, problem_html: str, day: int, allow_sleep: bool) -> str:
    instructions = build_agent_instructions(day=day, allow_sleep=allow_sleep)
    problem_section = f"\n\nProblem:\n\n{problem_html}"
    return "Solve this Advent of Code problem.\n\n" + "\n\n".join(instructions) + problem_section
