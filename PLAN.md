# GitHub Research Agent — Portfolio Project 3 (system_with_tool_call)

## Context
Project 3 is about tool calling. Each day the agent reads github.com/trending, researches every repo it hasn't analysed before, judges whether a product could be built on that repo and who would pay for it, and writes everything into a dated PDF.

Choices the user made:
- **Model:** Amazon Bedrock.
- **Agent framework:** LangChain v1 `create_agent`, which runs on LangGraph.
- **Where it runs:** locally only. Deploying to AWS is left for the later `agent_to-production` project.
- **Depth:** every new repo gets a full analysis.
- **Memory:** a record of repos already analysed, so they're skipped on later days.

**Learning style:** follow the guided style. For each step Claude shows the complete code in chat and explains it. The user types it in and runs it, then Claude reviews the result. Claude does not write the project files.

## Architecture
The fixed steps are plain Python. The agent is used only for researching each repo, where real decisions happen:

```
main.py (plain code)
  1. trending.py   scrape github.com/trending → ~25 repos (name, desc, lang, stars, stars_today)
  2. history.py    record today's sightings; split into NEW vs SEEN-BEFORE (SQLite)
  3. for each NEW repo → agent.py: fresh create_agent run with tools → RepoAnalysis (Pydantic)
       tools: get_repo_info · get_readme · list_files · read_file · get_recent_issues · web_search
       errors stay per repo: a failed repo is NOT saved, so it's retried tomorrow
  4. history.py    save each analysis (JSON) to SQLite
  5. report.py     PDF: summary table + one page per new repo + "seen before" appendix (from DB, no LLM)
```

## Key decisions
- **Model:** Amazon Nova 2 Lite, `global.amazon.nova-2-lite-v1:0` called from ap-southeast-2 (Sydney) through `langchain_aws.ChatBedrockConverse`.
  - It's Amazon's own model, so there's no Marketplace subscription or use-case form. It fits the free plan, supports tool use and has a 1M-token context.
  - **Why Sydney:** the account was made with AWS's new sign-up ("projects"), which fixes the home region from the contact address. Free-plan accounts of this type don't support cross-region features, so the project stays in its home region.
  - **Why `global.`:** called from Sydney, Nova 2 Lite has no Australia-only or Asia-only profile (`au.` is an invalid ID). The global profile can process requests in any commercial region, which is fine because only public GitHub data is sent.
  - The model ID and region live in `config.py` and `.env`, so they can be swapped later, for example to Claude Haiku 4.5 once Anthropic access is enabled.
- **Throttling:** pass `botocore.config.Config(retries={"mode": "adaptive", "max_attempts": 10})` to the model, and always set `maxTokens`. Bedrock sets aside input tokens plus `maxTokens` from the quota before each call, so an unset `maxTokens` wastes quota.
- **Structured output:** `create_agent(..., response_format=RepoAnalysis)` and read `result["structured_response"]`. If Bedrock rejects provider-native structured output, fall back to `ToolStrategy(RepoAnalysis)`, which works with any model that can call tools.
- **Prompt rules against generic ideas:**
  - Score with a rubric: pain point, who pays, maturity, competition.
  - Every claim must cite evidence from the repo.
  - "No opportunity" is an allowed answer, for awesome-lists, courses, dotfiles and similar.
  - Check the license first:
    - MIT, Apache or BSD: commercial use is OK.
    - GPL or AGPL: copyleft, which limits closed or hosted products.
    - No license: the code can't legally be used.
  - Always write in English.
- **Guardrails in the tools:**
  - Truncate tool output: README to about 8k characters, other files to about 4k, to keep token use down.
  - Tools return error strings instead of raising, so the agent can recover from a 404.
  - Set a recursion limit (about 10 tool calls per repo).
  - Limit the paid tool in code, not just in the prompt: `ToolCallLimitMiddleware(tool_name="web_search", run_limit=2)` (Step 5).
  - Start a fresh agent for each repo, so analyses don't leak into each other.
- **GitHub access:**
  - Use the REST API with a fine-grained, read-only token from `.env`. That allows 5,000 requests/hour instead of 60.
  - The trending page has no API, so scrape it with `requests` and BeautifulSoup. This can break when GitHub changes the page; noted in the README.
- **Web search:** use `langchain-tavily` to check for competitors. The free tier is 1,000 searches/month, enough because skipping known repos means only a few new repos per day after the first run.
- **History store:** SQLite, from the Python standard library, at `data/history.db`. It has two tables:
  - `analyses(repo PK, analysed_on, verdict, score, license, analysis_json)`
  - `sightings(date, repo, rank, stars_today)`

  `sightings` lets the PDF say things like "trending 4 days, analysed Nov 3". Re-analysing older repos is left as a stretch goal.
- **PDF:** `fpdf2` (pure Python). Bundle a DejaVuSans TTF in `assets/fonts/` for Unicode. Strip emoji, and use the model's English summary instead of the raw descriptions, which are sometimes in Chinese.

## Files (in `system_with_tool_call/github_research_agent/`)
- `pyproject.toml`: created with `uv init --no-workspace --python 3.12`, because a plain `uv init` would join the home folder's uv workspace. Dependencies: `langchain`, `langchain-aws`, `langchain-tavily`, `requests`, `beautifulsoup4`, `python-dotenv`, `fpdf2`, `pydantic`.
- `.env` (gitignored): `GITHUB_TOKEN`, `TAVILY_API_KEY`, `AWS_REGION=ap-southeast-2`, and `AWS_PROFILE` if needed. AWS keys are not stored here; they live in `~/.aws/credentials` from `aws configure`.
- `.env.example` (committed): the same variable names with empty values, so anyone who clones the repo knows which keys to add.
- `.gitignore` covers `.env`, `.venv/`, `__pycache__/`, `data/`, `reports/` and `.DS_Store`.
- Code is grouped into packages by job. Every folder has an empty `__init__.py`:
  ```
  main.py                  the daily run (uv run main.py)
  config.py                settings, kept at the top so every module can import it
  sources/trending.py      Step 3: scrape github.com/trending
  tools/github_tools.py    Step 4: GitHub API tools for the agent
  tools/search_tools.py    Step 7: Tavily competitor search
  agent/schemas.py         Step 6a: RepoAnalysis (Pydantic)
  agent/researcher.py      Step 5: the agent
  storage/history.py       Step 8: SQLite history
  reporting/pdf_report.py  Step 10: the PDF
  assets/fonts/            PDF font
  ```
- Run a single module from the project root with `uv run python -m <package>.<module>` (e.g. `uv run python -m tools.github_tools`). That keeps the root on Python's import path, so `from config import ...` works everywhere.
- Output goes to `reports/YYYY-MM-DD.pdf`. Commit one sample PDF for the portfolio.

`agent/schemas.py` defines `RepoAnalysis` with these fields: `repo`, `one_line_summary`, `category` (library/framework/app/tool/model/list/tutorial/other), `license`, `license_commercial` (permissive/copyleft/none/unknown), `verdict` (strong/maybe/none), `opportunity_score` (1–10), `business_idea`, `product_type`, `target_customers: list[TargetCustomer(segment, pain_point, why_they_pay)]`, `competitors`, `risks` and `evidence`.

## Step-by-step roadmap (one step per session chunk)
0. **AWS and keys setup.**
   - Create an IAM user (`bedrock-dev`) rather than using the root account, and run `aws configure` with region ap-southeast-2. Its policy allows `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`, plus the AWS-managed `ServiceQuotasReadOnlyAccess` for checking quotas.
   - Try Nova 2 Lite in the Bedrock playground. This also earns the $20 Bedrock credit activity.
   - Create an AWS Budget alert at about $5. This earns the $20 Budgets credit activity.
   - Get a GitHub fine-grained token and a Tavily key.
1. **Project setup.** `uv init --no-workspace --python 3.12`, add the dependencies, `.gitignore`, `.env`, `config.py`.
2. **Hello Bedrock.** Call `ChatBedrockConverse.invoke` once to prove the credentials and model access work.
3. **`trending.py`.** Scrape and parse the page; the smoke test prints about 25 repos.
4. **`github_tools.py`.** Write plain functions first and test them. Then wrap them with `@tool` and explain how the docstring and type hints become the tool schema.
5. **First agent.** `create_agent` with the GitHub tools on one repo, returning free text. Stream or print the messages to watch the model choose tools. This is the key learning moment of the project.
6. **Structured output.** `schemas.py`, `response_format`, and the rubric and license rules in the system prompt.
7. **`search_tools.py`.** Add the Tavily competitor check.
8. **`history.py`.** SQLite setup, sightings, the new-vs-seen split, saving analyses.
9. **`main.py`.** The orchestrator loop: per-repo error handling, logging, a run summary.
10. **`report.py`.** The PDF: cover with counts, summary table sorted by score, a page per repo, the "seen before" appendix.
11. **README.** Architecture diagram, design decisions (why only part of it is an agent, the license check, skipping known repos), setup, limits, sample PDF.

**Order while waiting for Bedrock.** Decision (2026-11-09): no stand-in model provider; the project stays on Bedrock. Everything that doesn't need a model is built first:
- **Now, no model needed:** 3 → 4 → 6a (`schemas.py`, the Pydantic schema only) → 7 → 8 → 10 → 9a (`main.py` with a *fake* analyser that returns a hand-made `RepoAnalysis`, so the whole pipeline runs end to end and produces a real PDF).
- **Once Bedrock access opens:** 2 → 5 → 6b (structured output in the agent) → 9b (swap the fake analyser for the real agent) → 11.

Stretch goals: re-analyse after N days or when stars jump; LangSmith tracing (leads into the eval_and_observability project); a daily local run with launchd or cron; deploy later with Lambda, EventBridge and S3.

## Progress
- [x] **Step 0:** IAM user, AWS CLI, budget alert, GitHub token, Tavily key. The Bedrock test is blocked by quotas (see below).
- [x] **Step 1:** uv project, `.gitignore`, `.env`, `config.py`. `uv run config.py` passes.
- [ ] **Step 2:** blocked until AWS opens Bedrock access for this account (see below).
- [x] **Step 3:** `sources/trending.py`. The daily list varies in length (9–11 repos seen, not 25).
- [x] **Step 4:** `tools/github_tools.py`: 5 tools, errors returned as text, authenticated (5,000 requests/hour).
- [x] **Step 6a:** `agent/schemas.py`: `RepoAnalysis` and `TargetCustomer` with `Literal` choices and a 1–10 score. Rule: the model fills in judgments; our code overwrites facts it already knows (`repo`, `license`).
- [x] **Step 7:** `tools/search_tools.py`: `web_search` wraps Tavily (short results, errors as text). `config.py` now loads `.env` by exact path.
- [ ] **Step 8:** `storage/history.py` (next).

## Setup issues and lessons learned
These are worth keeping for the README:
1. **"Your account is currently being verified"** (AccessDeniedException): every brand-new AWS account is checked first. It cleared within about 2 hours.
2. **"Too many tokens per day"** (ThrottlingException), even on a 20-token test:
   - It wasn't the region, IAM or `maxTokens`. Calls failed the same way in us-east-1 and ap-southeast-2 with three different model IDs.
   - Reading the quotas showed the cause. The account-wide "Cross-Model Max Tokens Per Day" was 150M, but **every per-model quota was 0**: Nova 2 Lite tokens per day, tokens per minute and requests per minute. New accounts can start below AWS's defaults.
   - Tried: in Service Quotas (Sydney), requested increases for "Global cross-region model inference tokens per minute for Amazon Nova 2 Lite" and "... requests per minute ...". AWS **declined** the same day: "unable to approve your request at this time … model access may depend on … account history and usage patterns … subject to change automatically as time passes."
   - Many re:Post threads in 2026 describe the same thing, and AWS's usual advice is to build account history over at least one billing cycle.
   - Next tries:
     - An "Account and billing" support case asking for account verification and setup of the default quotas (not an "increase").
     - The Explore AWS credit activities (Lambda, EC2, RDS) as normal usage.
     - Ask again in early December, after the first billing cycle.
3. **Throttle versus access denied:** a throttle means the request reached the model and was refused by a quota, so IAM and model access are fine. Access denied points to permissions or model access.
4. **New AWS sign-up and regions:** the home region is fixed by the contact country (Sydney here), and Free-plan accounts don't support cross-region features. Check the region in AWS Settings, under Projects, then Additional info.

## Verification
- Each module has an `if __name__ == "__main__":` smoke test that's run as its step is finished.
- End to end: `uv run main.py` writes `reports/<today>.pdf`. Open it and check that the counts (trending, new, skipped) match the log.
- Run it a second time on the same day. Every repo should be skipped, with zero Bedrock calls in the log, and the PDF should show them in the "seen before" appendix.
- Check a repo with no license or an AGPL license. The analysis should flag the license limit.
- Check the AWS Billing console. Bedrock usage should be drawn from credits and stay under the budget alert.
