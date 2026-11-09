"""Web search tool, so the agent can check whether competitors already exist.

We wrap Tavily's LangChain tool in our own @tool to control what the model
sees: short readable results (fewer tokens), errors as text, and a
description written for our use case.
"""
from langchain.tools import tool
from langchain_tavily import TavilySearch

from config import MAX_SEARCH_RESULTS  # importing config also loads .env (TAVILY_API_KEY)

_tavily = TavilySearch(max_results=MAX_SEARCH_RESULTS, topic="general", search_depth="basic")


@tool
def web_search(query: str) -> str:
    """Search the web. Use it to check whether companies or products already
    offer what a business idea proposes (competitors, hosted versions, pricing).
    Write a specific query, e.g. "hosted username monitoring API for brand protection".
    Use at most 2 searches per repository."""
    try:
        result = _tavily.invoke({"query": query})
    except Exception as e:  # network problems, invalid key...
        return f"ERROR: search failed ({type(e).__name__}: {e})"

    # Tavily reports some errors as {"error": ...} instead of raising
    if "error" in result:
        return f"ERROR: search failed ({result['error']})"

    items = result.get("results", [])
    if not items:
        return "No results found."

    lines = []
    for r in items:
        title = (r.get("title") or "")[:120]
        snippet = " ".join((r.get("content") or "").split())[:300]  # collapse whitespace, keep it short
        lines.append(f"- {title}\n  {r.get('url')}\n  {snippet}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== What the model sees ===")
    print(f"- {web_search.name}{web_search.args}")
    print(f"    {web_search.description.splitlines()[0]}")

    print("\n=== One real search (uses 1 Tavily credit) ===")
    out = web_search.invoke({"query": "hosted username search API for brand protection teams"})
    print(out)
    print(f"\n({len(out):,} characters go to the model)")

    print("\n=== Errors come back as text (no credit used) ===")
    print(web_search.invoke({"query": ""}))
