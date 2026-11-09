"""The structured result the agent must return for each repository.

The agent's final answer is not free text: it must fill in this form.
Pydantic checks every field, so a bad answer (score 11, unknown verdict)
fails loudly instead of ending up in the PDF.
"""
from typing import Literal

from pydantic import BaseModel, Field


class TargetCustomer(BaseModel):
    """One group of people who would pay for the product."""

    segment: str = Field(description="Who they are, specifically, e.g. 'small e-commerce teams on Shopify'.")
    pain_point: str = Field(description="The problem they have today that the product would solve.")
    why_they_pay: str = Field(description="Why they would pay instead of running the free open-source repo themselves.")


class RepoAnalysis(BaseModel):
    """Business-opportunity analysis of one trending GitHub repository."""

    repo: str = Field(description='The repository as "owner/name".')
    one_line_summary: str = Field(description="What the project does, in one plain-English sentence.")
    category: Literal["library", "framework", "app", "tool", "model", "list", "tutorial", "other"] = Field(
        description="What kind of repository this is. 'list' = awesome-lists and link collections; "
                    "'tutorial' = courses and learning material; 'model' = AI model weights or training code.")
    license: str = Field(description="The license exactly as get_repo_info reported it, e.g. 'MIT License (MIT)'.")
    license_commercial: Literal["permissive", "copyleft", "none", "unknown"] = Field(
        description="permissive = MIT/Apache/BSD, commercial use OK; copyleft = GPL/AGPL, limits closed or hosted "
                    "products; none = no license, the code cannot legally be reused; unknown = not detected or unclear.")
    verdict: Literal["strong", "maybe", "none"] = Field(
        description="Is there a real business opportunity? 'none' is a valid and common answer.")
    opportunity_score: int = Field(ge=1, le=10, description="1 = no opportunity, 10 = exceptional. Follow the scoring rubric.")
    business_idea: str = Field(description="The product to build on top of this repo. If verdict is 'none', say briefly why there is none.")
    product_type: str = Field(description="e.g. 'hosted SaaS', 'paid API', 'IDE plugin', 'managed service', 'support/consulting', or '-'.")
    target_customers: list[TargetCustomer] = Field(description="1-3 customer groups. Empty list if verdict is 'none'.")
    competitors: list[str] = Field(description="Existing products that already solve this problem. Empty list if none found.")
    risks: list[str] = Field(description="Main risks: license limits, strong competitors, the repo owner launching the same product, etc.")
    evidence: list[str] = Field(description="Facts behind the judgment, each with its source, e.g. 'README: supports 400+ sites'.")


if __name__ == "__main__":
    import json

    from pydantic import ValidationError

    # A hand-written example. Later it doubles as test data for the database and the PDF.
    example = RepoAnalysis(
        repo="sherlock-project/sherlock",
        one_line_summary="A command-line tool that finds accounts with a given username across 400+ social networks.",
        category="tool",
        license="MIT License (MIT)",
        license_commercial="permissive",
        verdict="maybe",
        opportunity_score=6,
        business_idea="A hosted username-monitoring service with an API, scheduled scans and alerts, "
                      "so teams don't have to run and maintain the CLI themselves.",
        product_type="hosted SaaS + paid API",
        target_customers=[
            TargetCustomer(
                segment="Brand-protection and trust & safety teams",
                pain_point="Impersonation accounts appear on many sites and are found too late",
                why_they_pay="Continuous monitoring and alerts instead of manual CLI runs",
            ),
        ],
        competitors=["Namechk", "WhatsMyName web app"],
        risks=["Sites change often and break detection (high maintenance)",
               "Legal and privacy limits on OSINT tools in some countries"],
        evidence=["get_repo_info: 105,938 stars, MIT license, last push 2026-11-09",
                  "get_recent_issues: many 'false positive/negative' reports, so detection breaks often"],
    )

    print("=== A valid analysis as JSON (this is what we'll store in SQLite) ===")
    print(example.model_dump_json(indent=2)[:500], "...")

    print("\n=== Pydantic rejects bad answers ===")
    bad = example.model_dump() | {"opportunity_score": 11, "verdict": "very strong"}
    try:
        RepoAnalysis.model_validate(bad)
    except ValidationError as e:
        print(e)

    print("\n=== The JSON schema the model will be asked to fill (start) ===")
    print(json.dumps(RepoAnalysis.model_json_schema(), indent=2)[:700], "...")

    print("\n=== Round trip: JSON text back into an object ===")
    again = RepoAnalysis.model_validate_json(example.model_dump_json())
    print("identical:", again == example, "| first segment:", again.target_customers[0].segment)
