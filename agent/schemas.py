"""The structured result the agent must return for each repository.

The agent's final answer is not free text: it must fill in this form.
The model gives its judgments (including the five rubric points); our code
adds the points up and sets the verdict, so the score is always consistent.
"""
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class TargetCustomer(BaseModel):
    """One group of people who would pay for the product."""

    segment: str = Field(description="Who they are, specifically, e.g. 'small e-commerce teams on Shopify'.")
    pain_point: str = Field(description="The problem they have today that the product would solve.")
    why_they_pay: str = Field(description="Why they would pay instead of running the free open-source repo themselves.")


class ScoreBreakdown(BaseModel):
    """The rubric points. Our code adds them up into the score and the verdict."""

    pain: int = Field(ge=0, le=3, description="0-3: a real problem, shown by evidence (issues, README, adoption), not assumed.")
    buyer: int = Field(ge=0, le=2, description="0-2: a clear buyer with a budget (businesses or professionals, not hobbyists).")
    maturity: int = Field(ge=0, le=2, description="0-2: mature, maintained, working software (not a demo, list or tutorial).")
    room: int = Field(ge=0, le=2, description="0 if a hosted version of this project is already sold (or the owner sells it); "
                                                "1 if large, well-funded alternatives exist; 2 only if no real alternative was found.")
    license: int = Field(ge=0, le=1, description="1 if the license is permissive, else 0.")


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
    score_breakdown: ScoreBreakdown = Field(description="Points for each rubric item. Be strict.")
    business_idea: str = Field(description="The product to build on top of this repo. If there is no opportunity, say briefly why.")
    product_type: str = Field(description="e.g. 'hosted SaaS', 'paid API', 'IDE plugin', 'managed service', 'support/consulting', or '-'.")
    target_customers: list[TargetCustomer] = Field(description="1-3 customer groups. Empty list if there is no opportunity.")
    competitors: list[str] = Field(description="Existing products that already solve this problem. Empty list if none found.")
    risks: list[str] = Field(description="Main risks: license limits, strong competitors, the repo owner launching the same product, etc.")
    evidence: list[str] = Field(description="Facts behind the judgment, each with its source, e.g. 'README: supports 400+ sites'.")

    @model_validator(mode="after")
    def _apply_rubric_rules(self):
        """A rubric rule code can check: 'room' may be 2 only if no competitor was found."""
        if self.competitors and self.score_breakdown.room > 1:
            self.score_breakdown.room = 1
        return self

    @computed_field
    @property
    def opportunity_score(self) -> int:
        """Total rubric points (1-10), with caps for no license and for lists/tutorials."""
        b = self.score_breakdown
        total = b.pain + b.buyer + b.maturity + b.room + b.license
        if self.license_commercial == "none":
            total = min(total, 3)
        if self.category in ("list", "tutorial"):
            total = min(total, 2)
        return max(1, total)

    @computed_field
    @property
    def verdict(self) -> Literal["strong", "maybe", "none"]:
        """Derived from the score: 7+ strong, 4-6 maybe, 3 or less none."""
        s = self.opportunity_score
        return "strong" if s >= 7 else "maybe" if s >= 4 else "none"


if __name__ == "__main__":
    from pydantic import ValidationError

    # A hand-written example (no model involved).
    example = RepoAnalysis(
        repo="sherlock-project/sherlock",
        one_line_summary="A command-line tool that finds accounts with a given username across 400+ social networks.",
        category="tool",
        license="MIT License (MIT)",
        license_commercial="permissive",
        score_breakdown=ScoreBreakdown(pain=2, buyer=2, maturity=1, room=2, license=1),
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

    print("=== Code computes the score and verdict ===")
    print("room given: 2, room after the rule (competitors exist):", example.score_breakdown.room)
    print("score:", example.opportunity_score, "| verdict:", example.verdict)

    print("\n=== What the model is asked to fill (score and verdict are NOT in it) ===")
    print(list(RepoAnalysis.model_json_schema()["properties"]))

    print("\n=== Pydantic rejects bad answers ===")
    bad = example.model_dump() | {"category": "awesome", "score_breakdown": {"pain": 5, "buyer": 2, "maturity": 2, "room": 0, "license": 1}}
    try:
        RepoAnalysis.model_validate(bad)
    except ValidationError as e:
        print(e)

    print("\n=== Saved JSON includes score and verdict, and loads back ===")
    saved = example.model_dump_json()
    again = RepoAnalysis.model_validate_json(saved)
    print("score in JSON:", f'"opportunity_score":{example.opportunity_score}' in saved,
          "| verdict in JSON:", f'"verdict":"{example.verdict}"' in saved, "| identical:", again == example)
