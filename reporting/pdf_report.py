"""Build the daily PDF report with fpdf2.

Pages: a summary table, one page per newly analysed repo, then repos
seen on earlier days and any that failed. Everything shown comes from
RepoAnalysis objects and the history database.
"""
import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from agent.schemas import RepoAnalysis
from config import BASE_DIR, REPORTS_DIR

FONT_DIR = BASE_DIR / "assets" / "fonts"
FONT = "DejaVu"
VERDICT_COLORS = {"strong": (22, 128, 61), "maybe": (180, 110, 0), "none": (120, 120, 120)}  # green, amber, grey

# Characters DejaVu Sans can't draw: Chinese/Japanese/Korean text and emoji.
_UNDRAWABLE = re.compile("[\u3000-\u9fff\uac00-\ud7af\uf900-\ufaff\ufe0f\U00010000-\U0010ffff]")


def clean(text) -> str:
    """Remove characters the font can't draw and tidy the spacing left behind."""
    text = " ".join(_UNDRAWABLE.sub("", str(text)).split())
    return re.sub(r"\s+([.,;:!?])", r"\1", text)  # "projects ." -> "projects."


class Report(FPDF):
    """An FPDF document with our fonts, header, footer and text helpers."""

    def __init__(self, day: str):
        super().__init__()
        self.day = day
        self.add_font(FONT, "", FONT_DIR / "DejaVuSans.ttf")
        self.add_font(FONT, "B", FONT_DIR / "DejaVuSans-Bold.ttf")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_title(f"GitHub trending opportunities {day}")

    def header(self):  # fpdf2 calls this automatically at the top of every page
        if self.page_no() > 1:
            self.set_font(FONT, "", 8)
            self.set_text_color(130)
            self.cell(0, 6, f"GitHub trending: business opportunities  |  {self.day}", align="R",
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(0)
            self.ln(2)

    def footer(self):  # ...and this at the bottom
        self.set_y(-12)
        self.set_font(FONT, "", 8)
        self.set_text_color(130)
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="C")  # {nb} = total pages
        self.set_text_color(0)

    def h1(self, text: str):
        self.set_font(FONT, "B", 18)
        self.multi_cell(0, 9, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def h2(self, text: str):
        self.ln(3)
        self.set_font(FONT, "B", 12)
        self.multi_cell(0, 7, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text: str, size: int = 10, indent: float = 0):
        self.set_font(FONT, "", size)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 5.5, clean(text), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullets(self, items: list[str], empty: str = "None found."):
        self.set_font(FONT, "", 10)
        if not items:
            self.multi_cell(0, 5.5, empty, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for item in items:
            self.cell(6, 5.5, "•")  # bullet, then the text starts 6 mm in, so wrapped lines line up
            self.multi_cell(0, 5.5, clean(item), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _summary_page(pdf: Report, analyses: list[RepoAnalysis], seen: list[dict], trending_count: int, failed: list[str]):
    pdf.add_page()
    pdf.h1("GitHub Trending: Business Opportunities")
    pdf.para(f"Date: {pdf.day}", size=11)
    pdf.para(f"Trending today: {trending_count}  |  Newly analysed: {len(analyses)}  |  "
             f"Seen on earlier days: {len(seen)}  |  Failed (retried tomorrow): {len(failed)}", size=11)

    pdf.h2("New repositories, best opportunities first")
    if not analyses:
        pdf.para("No new repositories today.")
        return
    pdf.set_font(FONT, "", 9)
    with pdf.table(col_widths=(62, 22, 20, 14, 32), line_height=6) as table:
        table.row(["Repository", "Category", "Verdict", "Score", "License use"])  # first row = header
        for a in analyses:
            table.row([clean(a.repo), a.category, a.verdict, f"{a.opportunity_score}/10", a.license_commercial])


def _repo_page(pdf: Report, a: RepoAnalysis):
    pdf.add_page()
    pdf.h1(a.repo)
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(0, 90, 200)
    pdf.cell(0, 5, f"https://github.com/{a.repo}", link=f"https://github.com/{a.repo}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0)
    pdf.ln(2)
    pdf.para(a.one_line_summary, size=11)

    pdf.ln(2)
    pdf.set_font(FONT, "B", 11)
    pdf.set_text_color(*VERDICT_COLORS[a.verdict])
    pdf.cell(0, 6, f"Verdict: {a.verdict.upper()}   Score: {a.opportunity_score}/10",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0)
    pdf.para(f"Category: {a.category}   |   License: {a.license} ({a.license_commercial})", size=9)

    pdf.h2("Business idea")
    pdf.para(a.business_idea)
    pdf.para(f"Product type: {a.product_type}", size=9)

    pdf.h2("Target customers")
    if not a.target_customers:
        pdf.para("None identified.")
    for c in a.target_customers:
        pdf.set_font(FONT, "B", 10)
        pdf.cell(6, 5.5, "•")
        pdf.multi_cell(0, 5.5, clean(c.segment), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.para(f"Pain point: {c.pain_point}", size=9, indent=6)
        pdf.para(f"Why they pay: {c.why_they_pay}", size=9, indent=6)

    pdf.h2("Competitors")
    pdf.bullets(a.competitors)
    pdf.h2("Risks")
    pdf.bullets(a.risks)
    pdf.h2("Evidence")
    pdf.bullets(a.evidence)


def _seen_page(pdf: Report, seen: list[dict], failed: list[str]):
    pdf.add_page()
    pdf.h1("Seen on earlier days")
    if not seen:
        pdf.para("None: every trending repository today was new.")
    else:
        pdf.para("Already analysed, so skipped today (no model cost). Details are in the earlier reports.", size=9)
        pdf.ln(2)
        pdf.set_font(FONT, "", 9)
        with pdf.table(col_widths=(70, 30, 20, 15, 25), line_height=6) as table:
            table.row(["Repository", "Analysed on", "Verdict", "Score", "Days trending"])
            for s in seen:
                table.row([clean(s["repo"]), s["analysed_on"], s["verdict"], f"{s['score']}/10", str(s["days_trending"])])
    if failed:
        pdf.h2("Failed today (will be retried tomorrow)")
        pdf.bullets(failed)


def build_report(day: str, analyses: list[RepoAnalysis], seen: list[dict], trending_count: int,
                 failed: list[str] | None = None, out_path: Path | None = None) -> Path:
    """Write the day's PDF and return its path (default: reports/<day>.pdf)."""
    failed = failed or []
    analyses = sorted(analyses, key=lambda a: a.opportunity_score, reverse=True)
    pdf = Report(day)
    _summary_page(pdf, analyses, seen, trending_count, failed)
    for a in analyses:
        _repo_page(pdf, a)
    _seen_page(pdf, seen, failed)
    out_path = out_path or REPORTS_DIR / f"{day}.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


if __name__ == "__main__":
    from agent.schemas import TargetCustomer

    # Hand-written sample data (no model involved). Note the emoji and
    # Chinese characters: clean() removes them so the font never fails.
    sherlock = RepoAnalysis(
        repo="sherlock-project/sherlock",
        one_line_summary="A command-line tool that finds accounts with a given username across 400+ social networks.",
        category="tool", license="MIT License (MIT)", license_commercial="permissive",
        verdict="maybe", opportunity_score=6,
        business_idea="A hosted username-monitoring service with an API, scheduled scans and alerts, "
                      "so teams don't have to run and maintain the CLI themselves.",
        product_type="hosted SaaS + paid API",
        target_customers=[TargetCustomer(segment="Brand-protection and trust & safety teams",
                                         pain_point="Impersonation accounts appear on many sites and are found too late",
                                         why_they_pay="Continuous monitoring and alerts instead of manual CLI runs")],
        competitors=["Namechk", "WhatsMyName web app"],
        risks=["Sites change often and break detection (high maintenance), so a hosted product needs "
               "a team that updates the site rules every week, which is a real ongoing cost",
               "Legal and privacy limits on OSINT tools in some countries"],
        evidence=["get_repo_info: 105,938 stars, MIT license, last push 2026-11-09",
                  "get_recent_issues: many 'false positive/negative' reports 🚀, so detection breaks often"],
    )
    awesome = RepoAnalysis(
        repo="example/awesome-ai-agents",
        one_line_summary="A curated list of links to AI agent projects 股票.",
        category="list", license="NOT DETECTED by GitHub", license_commercial="unknown",
        verdict="none", opportunity_score=1,
        business_idea="None: it is a list of links, there is no software to build a product on.",
        product_type="-", target_customers=[], competitors=[], risks=[],
        evidence=["get_readme: only links, no code", "list_files: README.md only"],
    )
    path = build_report(
        day="2026-11-09",
        analyses=[awesome, sherlock],  # deliberately unsorted: build_report sorts by score
        seen=[{"repo": "anthropics/skills", "analysed_on": "2026-11-08", "verdict": "none", "score": 2, "days_trending": 3}],
        trending_count=11,
        failed=["meta/astryx"],
        out_path=REPORTS_DIR / "sample.pdf",
    )
    print("wrote", path)
