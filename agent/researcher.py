"""The research agent: a LangChain agent that investigates one GitHub repo with tools.

create_agent builds the classic agent loop:
    model decides -> tools run -> results go back to the model -> ... -> final answer
"""
import sys
import time

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware

from agent.llm import get_model
from config import RECURSION_LIMIT
from tools.github_tools import GITHUB_TOOLS
from tools.search_tools import web_search

SYSTEM_PROMPT = """You are a startup analyst. You research one GitHub repository at a time with your tools,
then explain whether a business could be built on top of it and who would pay for it.

How to work:
- Always start with get_repo_info, then read the README with get_readme.
- Use list_files, read_file or get_recent_issues only when they would change your judgment.
- Use web_search to check whether competitors already sell the idea.
- Base every statement on what the tools returned. If something is unknown, say so."""


def build_agent():
    """Create the agent: model + tools + instructions + a code-enforced limit on paid searches."""
    return create_agent(
        model=get_model(),
        tools=[*GITHUB_TOOLS, web_search],
        system_prompt=SYSTEM_PROMPT,
        middleware=[ToolCallLimitMiddleware(tool_name="web_search", run_limit=2)],
    )


def _show(msg) -> None:
    """Print one message from the agent loop in a readable way."""
    if msg.type == "ai" and msg.tool_calls:
        for call in msg.tool_calls:
            print(f"[model] calls {call['name']}({call['args']})")
    elif msg.type == "tool":
        preview = " ".join(str(msg.content).split())[:110]
        print(f"[tool]  {msg.name} returned {len(str(msg.content)):,} chars: {preview}...")
    elif msg.type == "ai":
        print("\n[model] final answer:\n")
        print(msg.content)


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "sherlock-project/sherlock"
    agent = build_agent()
    question = (f"Research the GitHub repository {repo}. Is there a business opportunity in building "
                f"a product on top of it, and who would pay for it?")

    start = time.time()
    tokens_in = tokens_out = model_calls = 0
    # stream_mode="updates" gives us each step of the loop as it happens
    for step in agent.stream({"messages": [{"role": "user", "content": question}]},
                             config={"recursion_limit": RECURSION_LIMIT}, stream_mode="updates"):
        for node, update in step.items():
            for msg in (update or {}).get("messages", []):
                _show(msg)
                if msg.type == "ai" and msg.usage_metadata:
                    model_calls += 1
                    tokens_in += msg.usage_metadata["input_tokens"]
                    tokens_out += msg.usage_metadata["output_tokens"]

    print(f"\n--- {model_calls} model calls | {tokens_in:,} input + {tokens_out:,} output tokens "
          f"| {time.time() - start:.0f}s ---")
