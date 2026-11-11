"""The research agent: investigates one GitHub repo with tools and returns a RepoAnalysis.

create_agent runs the loop (model -> tools -> model ...); response_format makes the
final answer a validated RepoAnalysis instead of free text.
"""
import logging
import sys
import time
from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy

from agent.llm import get_model
from agent.schemas import RepoAnalysis
from config import RECURSION_LIMIT
from sources.trending import TrendingRepo
from tools.github_tools import GITHUB_TOOLS, get_repo_info
from tools.search_tools import web_search

log = logging.getLogger("research_agent.researcher")

SYSTEM_PROMPT = """You are a sceptical startup analyst. You research ONE GitHub repository with your tools and decide
whether a real business could be built on top of it. Most trending repositories are NOT business opportunities;
saying so is a good answer, not a failure.

How to research:
1. Call get_repo_info first, then get_readme.
2. Use list_files, read_file or get_recent_issues only when they would change your judgment.
3. Use web_search (max 2) to check whether companies already sell the idea. Name real competitors you found.
Only use these tools: get_repo_info, get_readme, list_files, read_file, get_recent_issues, web_search,
RepoAnalysis. There is no tool called "search"; use web_search.

License rules (from get_repo_info):
- MIT, Apache-2.0, BSD: license_commercial = "permissive".
- GPL, AGPL, LGPL, MPL: "copyleft" (closed or hosted products are limited).
- "none" only if there is no license anywhere (the code cannot legally be reused; our code then caps the score at 3).
- "NOT DETECTED", different licenses per folder, or unclear: "unknown". Explain it in `risks`.

Scoring: fill score_breakdown strictly, using the point definitions in the RepoAnalysis tool.
Our code adds the points up and sets the verdict (7+ strong, 4-6 maybe, 3 or less none), so be strict:
"strong" should be rare. For awesome-lists, tutorials, courses, dotfiles and prompt collections, use
category "list" or "tutorial".

Rules for the answer:
- Every claim must come from tool results; put the supporting facts in `evidence`, each with its source.
- Do not invent numbers (market sizes, prices, user counts) that no tool returned.
- Write in plain English, even if the repository is in another language.

Work efficiently: about 4-8 tool calls are enough. When you are done researching, finish by calling the
RepoAnalysis tool with your answer. Do not write the answer as plain text."""


def build_agent():
    """Model + tools + instructions + structured answer + a code-enforced limit on paid searches."""
    return create_agent(
        model=get_model(),
        tools=[*GITHUB_TOOLS, web_search],
        system_prompt=SYSTEM_PROMPT,
        response_format=ToolStrategy(RepoAnalysis),   # the answer = a call to a "RepoAnalysis" tool
        middleware=[ToolCallLimitMiddleware(tool_name="web_search", run_limit=2)],
    )


def _license_from_github(repo: str) -> str:
    """The license exactly as GitHub reports it: a fact, so code fills it, not the model."""
    for line in get_repo_info.invoke({"repo": repo}).splitlines():
        if line.startswith("License: "):
            return line.removeprefix("License: ")
    return "unknown"


def _parse_text_answer(text) -> RepoAnalysis:
    """Safety net: the model sometimes writes the JSON as text instead of calling the tool."""
    text = str(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise RuntimeError("the agent finished without returning a RepoAnalysis")
    return RepoAnalysis.model_validate_json(text[start:end + 1])  # still fully validated


def make_researcher() -> Callable[[TrendingRepo], RepoAnalysis]:
    """Build the agent once, and return a function that analyses one repo per call."""
    agent = build_agent()

    def research(repo: TrendingRepo) -> RepoAnalysis:
        start = time.time()
        # A brand-new conversation for every repo, so analyses never leak into each other.
        result = agent.invoke(
            {"messages": [{"role": "user", "content": f"Analyse the GitHub repository {repo.full_name}."}]},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        analysis = result.get("structured_response") or _parse_text_answer(result["messages"][-1].content)
        # Facts we already know beat the model's copy of them.
        analysis = analysis.model_copy(update={"repo": repo.full_name, "license": _license_from_github(repo.full_name)})

        ai = [m for m in result["messages"] if m.type == "ai" and m.usage_metadata]
        tools_used = [m.name for m in result["messages"] if m.type == "tool"]
        log.info("    %s: %s %d/10 | tools: %s | %d model calls, %s in + %s out tokens | %.0fs",
                 repo.full_name, analysis.verdict, analysis.opportunity_score, ", ".join(tools_used), len(ai),
                 f"{sum(m.usage_metadata['input_tokens'] for m in ai):,}",
                 f"{sum(m.usage_metadata['output_tokens'] for m in ai):,}", time.time() - start)
        return analysis

    return research


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("research_agent").setLevel(logging.INFO)
    names = sys.argv[1:] or ["sherlock-project/sherlock"]
    research = make_researcher()
    for name in names:
        repo = TrendingRepo(rank=0, full_name=name, url=f"https://github.com/{name}", description="",
                            language="", stars=0, forks=0, stars_today=0)
        try:
            a = research(repo)
            print(f"\n===== {a.repo} =====")
            print(f"category={a.category} | license={a.license} -> {a.license_commercial} | {a.verdict} {a.opportunity_score}/10")
            print("breakdown:", a.score_breakdown.model_dump())
            print("idea:", a.business_idea[:220])
            print("customers:", [c.segment for c in a.target_customers])
            print("competitors:", a.competitors[:5])
            print("risks:", [r[:80] for r in a.risks[:3]])
        except Exception as e:
            print(f"\n===== {name} FAILED: {type(e).__name__}: {str(e)[:300]}")
