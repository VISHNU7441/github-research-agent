"""GitHub REST API helpers, exposed to the agent as LangChain tools.

Every tool returns plain text, because that is what the model reads.
Tools never raise: errors come back as text, so the agent can react
(for example, try another path) instead of the whole run crashing.
"""
import base64

import requests
from langchain.tools import tool

from config import (GITHUB_API, GITHUB_TOKEN, HTTP_TIMEOUT,
                    MAX_FILE_CHARS, MAX_ISSUES, MAX_README_CHARS)

# One Session reuses the connection and sends these headers on every call.
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {GITHUB_TOKEN}",    # 5,000 requests/hour instead of 60
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "github-research-agent (learning project)",
})


# ---------- small helpers (the leading _ means "internal") ----------

def _get(path: str, params: dict | None = None):
    """GET an API path such as '/repos/owner/name' and return the JSON."""
    response = session.get(f"{GITHUB_API}{path}", params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _error(e: Exception) -> str:
    """Turn an exception into a short message the model can understand."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = e.response.status_code
        if code == 404:
            return "ERROR: not found (404). Check the repo name or the file path."
        if code in (403, 429):
            return f"ERROR: GitHub refused the request ({code}), probably a rate limit. Try fewer calls."
        return f"ERROR: GitHub returned HTTP {code}."
    return f"ERROR: {type(e).__name__}: {e}"


def _truncate(text: str, limit: int) -> str:
    """Cut long text so we don't send (and pay for) huge files."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated, {len(text) - limit:,} more characters not shown]"


def _decode(content_b64: str) -> str:
    """The contents API returns files base64-encoded inside the JSON."""
    return base64.b64decode(content_b64).decode("utf-8")


# ---------- the tools the agent can call ----------

@tool
def get_repo_info(repo: str) -> str:
    """Get basic facts about a GitHub repository: description, stars, forks,
    open issues, main language, LICENSE, topics, creation and last-push dates.
    Call this first for every repository. `repo` must be "owner/name"."""
    try:
        d = _get(f"/repos/{repo}")
    except Exception as e:
        return _error(e)

    lic = d.get("license") or {}
    if lic:
        license_text = f"{lic.get('name')} ({lic.get('spdx_id')})"
    else:
        license_text = "NOT DETECTED by GitHub (no recognised LICENSE file at the top level)"

    return "\n".join([
        f"Repository: {d['full_name']}",
        f"Description: {d.get('description') or '-'}",
        f"Homepage: {d.get('homepage') or '-'}",
        f"Stars: {d['stargazers_count']:,} | Forks: {d['forks_count']:,} | Open issues: {d['open_issues_count']:,}",
        f"Main language: {d.get('language') or '-'}",
        f"License: {license_text}",
        f"Topics: {', '.join(d.get('topics') or []) or '-'}",
        f"Created: {d['created_at'][:10]} | Last push: {d['pushed_at'][:10]}",
        f"Archived: {'yes' if d.get('archived') else 'no'}",
    ])


@tool
def get_readme(repo: str) -> str:
    """Get the README of a GitHub repository (cut to the first part if long).
    Use it to learn what the project does and who it is for. `repo` is "owner/name"."""
    try:
        d = _get(f"/repos/{repo}/readme")
        return _truncate(_decode(d["content"]), MAX_README_CHARS)
    except Exception as e:
        return _error(e)


@tool
def list_files(repo: str, path: str = "") -> str:
    """List the files and folders at one path of a GitHub repository.
    Leave `path` empty for the top level, or pass a folder like "src" or "docs".
    Use it to see how the project is built (package.json, pyproject.toml, Dockerfile...)."""
    try:
        items = _get(f"/repos/{repo}/contents/{path}")
    except Exception as e:
        return _error(e)
    if isinstance(items, dict):  # the API returns a dict for a file, a list for a folder
        return f"'{path}' is a file, not a folder. Use read_file to read it."

    lines = []
    # folders first, then files, alphabetically; at most 100 entries
    for item in sorted(items, key=lambda i: (i["type"] != "dir", i["name"].lower()))[:100]:
        if item["type"] == "dir":
            lines.append(f"[dir]  {item['path']}/")
        else:
            lines.append(f"[file] {item['path']} ({item.get('size', 0):,} bytes)")
    return "\n".join(lines) or "(empty folder)"


@tool
def read_file(repo: str, path: str) -> str:
    """Read one text file from a GitHub repository, e.g. "package.json",
    "pyproject.toml" or "docs/pricing.md". Long files are cut short.
    Use list_files first to find the exact path."""
    try:
        d = _get(f"/repos/{repo}/contents/{path}")
    except Exception as e:
        return _error(e)
    if isinstance(d, list):
        return f"'{path}' is a folder. Use list_files to see what is inside."
    if d.get("encoding") != "base64" or "content" not in d:
        return f"'{path}' is too large or has no readable content."
    try:
        text = _decode(d["content"])
    except UnicodeDecodeError:
        return f"'{path}' is a binary file (image, archive...), not text."
    return _truncate(text, MAX_FILE_CHARS)


@tool
def get_recent_issues(repo: str) -> str:
    """List the most-discussed open issues of a GitHub repository (title,
    comment count, labels). Use it to find what users struggle with or ask
    for: real pain points are evidence for a business idea. `repo` is "owner/name"."""
    try:
        items = _get(f"/repos/{repo}/issues",
                     params={"state": "open", "sort": "comments",
                             "direction": "desc", "per_page": MAX_ISSUES * 2})
    except Exception as e:
        return _error(e)

    # GitHub's issues endpoint also returns pull requests; drop them
    issues = [i for i in items if "pull_request" not in i][:MAX_ISSUES]
    if not issues:
        return "No open issues."
    lines = []
    for i in issues:
        labels = ", ".join(label["name"] for label in i.get("labels", [])) or "-"
        lines.append(f"#{i['number']} [{i['comments']} comments] {i['title']} (labels: {labels})")
    return "\n".join(lines)


# The agent (Step 5) will receive this list.
GITHUB_TOOLS = [get_repo_info, get_readme, list_files, read_file, get_recent_issues]


if __name__ == "__main__":
    repo = "sherlock-project/sherlock"

    print("=== What the model sees (name + arguments + description) ===")
    for t in GITHUB_TOOLS:
        print(f"- {t.name}{t.args}")
        print(f"    {t.description.splitlines()[0]}")

    print("\n=== get_repo_info ===")
    print(get_repo_info.invoke({"repo": repo}))
    print("\n=== get_readme (first 300 chars) ===")
    print(get_readme.invoke({"repo": repo})[:300])
    print("\n=== list_files ===")
    print(list_files.invoke({"repo": repo}))
    print("\n=== read_file pyproject.toml (first 300 chars) ===")
    print(read_file.invoke({"repo": repo, "path": "pyproject.toml"})[:300])
    print("\n=== get_recent_issues ===")
    print(get_recent_issues.invoke({"repo": repo}))
    print("\n=== errors come back as text ===")
    print(get_repo_info.invoke({"repo": "nobody-xyz-123/does-not-exist"}))
    print(read_file.invoke({"repo": repo, "path": "docs"}))
