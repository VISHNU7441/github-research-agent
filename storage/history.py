"""SQLite memory: which repos were trending, and which we've analysed.

This is what lets the daily run skip repos analysed on earlier days,
so the model only spends tokens on new ones.
"""
import sqlite3
from pathlib import Path

from agent.schemas import RepoAnalysis
from config import DB_PATH
from sources.trending import TrendingRepo

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    repo          TEXT PRIMARY KEY,   -- "owner/name": one analysis per repo
    analysed_on   TEXT NOT NULL,      -- date as "YYYY-MM-DD"
    verdict       TEXT NOT NULL,      -- strong / maybe / none
    score         INTEGER NOT NULL,   -- 1-10
    license       TEXT,
    analysis_json TEXT NOT NULL       -- the full RepoAnalysis as JSON
);

CREATE TABLE IF NOT EXISTS sightings (
    date        TEXT NOT NULL,        -- a day the repo was on the trending page
    repo        TEXT NOT NULL,
    rank        INTEGER NOT NULL,
    stars_today INTEGER NOT NULL,
    PRIMARY KEY (date, repo)          -- at most one row per repo per day
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the file and tables on first use."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row      # rows work like dicts: row["repo"]
    conn.executescript(SCHEMA)          # IF NOT EXISTS makes this safe every time
    return conn


def record_sightings(conn: sqlite3.Connection, repos: list[TrendingRepo], day: str) -> None:
    """Remember which repos were trending on `day`. Safe to run twice the same day."""
    with conn:  # one transaction: all rows are saved, or none
        conn.executemany(
            "INSERT OR REPLACE INTO sightings (date, repo, rank, stars_today) VALUES (?, ?, ?, ?)",
            [(day, r.full_name, r.rank, r.stars_today) for r in repos],
        )


def split_new_and_seen(conn: sqlite3.Connection, repos: list[TrendingRepo]) -> tuple[list[TrendingRepo], list[TrendingRepo]]:
    """Split today's repos into (never analysed, analysed on an earlier day)."""
    analysed = {row["repo"] for row in conn.execute("SELECT repo FROM analyses")}
    new = [r for r in repos if r.full_name not in analysed]
    seen = [r for r in repos if r.full_name in analysed]
    return new, seen


def save_analysis(conn: sqlite3.Connection, analysis: RepoAnalysis, day: str) -> None:
    """Store one finished analysis (replaces an older one for the same repo)."""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO analyses (repo, analysed_on, verdict, score, license, analysis_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (analysis.repo, day, analysis.verdict, analysis.opportunity_score,
             analysis.license, analysis.model_dump_json()),
        )


def load_analysis(conn: sqlite3.Connection, repo: str) -> RepoAnalysis | None:
    """Load a stored analysis back as a RepoAnalysis object, or None if never analysed."""
    row = conn.execute("SELECT analysis_json FROM analyses WHERE repo = ?", (repo,)).fetchone()
    return RepoAnalysis.model_validate_json(row["analysis_json"]) if row else None


def history_for(conn: sqlite3.Connection, repo: str) -> dict:
    """What we know about a repo from earlier days (for the PDF's 'seen before' list)."""
    row = conn.execute(
        """
        SELECT a.analysed_on, a.verdict, a.score,
               (SELECT COUNT(*) FROM sightings s WHERE s.repo = a.repo) AS days_trending
        FROM analyses a
        WHERE a.repo = ?
        """,
        (repo,),
    ).fetchone()
    return dict(row) if row else {}


if __name__ == "__main__":
    # Test on an in-memory database, so the real data/history.db stays untouched.
    def fake_repo(name: str, rank: int) -> TrendingRepo:
        return TrendingRepo(rank=rank, full_name=name, url=f"https://github.com/{name}",
                            description="", language="Python", stars=1000, forks=10, stars_today=100)

    def fake_analysis(name: str) -> RepoAnalysis:
        return RepoAnalysis(
            repo=name, one_line_summary="Test summary.", category="tool",
            license="MIT License (MIT)", license_commercial="permissive",
            verdict="maybe", opportunity_score=6, business_idea="Test idea.",
            product_type="hosted SaaS", target_customers=[], competitors=[], risks=[], evidence=[],
        )

    conn = connect(":memory:")

    print("=== Day 1: two repos trending, we analyse sherlock only ===")
    day1 = [fake_repo("sherlock-project/sherlock", 1), fake_repo("anthropics/skills", 2)]
    record_sightings(conn, day1, "2026-11-09")
    new, seen = split_new_and_seen(conn, day1)
    print("new: ", [r.full_name for r in new])
    print("seen:", [r.full_name for r in seen])
    save_analysis(conn, fake_analysis("sherlock-project/sherlock"), "2026-11-09")

    print("\n=== Day 2: sherlock again + a new repo ===")
    day2 = [fake_repo("sherlock-project/sherlock", 3), fake_repo("anthropics/skills", 1), fake_repo("meta/astryx", 2)]
    record_sightings(conn, day2, "2026-11-10")
    record_sightings(conn, day2, "2026-11-10")  # running twice the same day must not double-count
    new, seen = split_new_and_seen(conn, day2)
    print("new: ", [r.full_name for r in new])
    print("seen:", [r.full_name for r in seen])
    print("history of sherlock:", history_for(conn, "sherlock-project/sherlock"))

    loaded = load_analysis(conn, "sherlock-project/sherlock")
    print("\nloaded back as RepoAnalysis:", type(loaded).__name__, "| verdict:", loaded.verdict, "| score:", loaded.opportunity_score)
    print("never analysed ->", load_analysis(conn, "meta/astryx"))
    print("sightings rows:", conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0], "(expected 5: 2 on day 1 + 3 on day 2)")
