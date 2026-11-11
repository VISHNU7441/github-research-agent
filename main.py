"""Daily run: trending -> skip known repos -> research new ones -> save -> PDF.

The research step is passed in as a function (an "analyser"), so run() doesn't
care how a repo gets analysed. Today that's the Bedrock agent.
"""
import argparse
import logging
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from agent.schemas import RepoAnalysis
from config import DB_PATH, REPORTS_DIR
from reporting.pdf_report import build_report
from sources.trending import TrendingRepo, fetch_trending
from storage import history

log = logging.getLogger("research_agent")

# Any function that takes a TrendingRepo and returns a RepoAnalysis can be the analyser.
Analyser = Callable[[TrendingRepo], RepoAnalysis]


def run(analyse: Analyser, db_path: Path, report_path: Path, day: str, limit: int | None = None) -> Path:
    """Run the whole pipeline for one day and return the PDF path."""
    started = time.time()
    conn = history.connect(db_path)

    repos = fetch_trending()
    history.record_sightings(conn, repos, day)
    new, seen = history.split_new_and_seen(conn, repos)

    # Repos already analysed earlier TODAY (the job was re-run) belong in today's report, not "seen before".
    analysed_today = [r for r in seen if history.history_for(conn, r.full_name)["analysed_on"] == day]
    seen = [r for r in seen if r not in analysed_today]

    if limit is not None:  # research only the first N new repos (cheap testing)
        new = new[:limit]
    log.info("Trending: %d | new: %d | done earlier today: %d | seen on earlier days: %d",
             len(repos), len(new), len(analysed_today), len(seen))

    analyses = [history.load_analysis(conn, r.full_name) for r in analysed_today]
    failed = []
    for i, repo in enumerate(new, start=1):
        log.info("[%d/%d] researching %s", i, len(new), repo.full_name)
        try:
            analysis = analyse(repo)
            # Never trust the analyser with a fact we already know: force the exact repo name.
            analysis = analysis.model_copy(update={"repo": repo.full_name})
            history.save_analysis(conn, analysis, day)
            analyses.append(analysis)
        except Exception as e:  # one bad repo must not stop the whole run
            log.warning("    failed (%s: %s), will retry tomorrow", type(e).__name__, str(e)[:200])
            failed.append(repo.full_name)

    seen_rows = [{"repo": r.full_name, **history.history_for(conn, r.full_name)} for r in seen]
    path = build_report(day, analyses, seen_rows, trending_count=len(repos), failed=failed, out_path=report_path)
    conn.close()
    log.info("Done in %.0fs: %d in report, %d failed, %d seen before. Report: %s",
             time.time() - started, len(analyses), len(failed), len(seen), path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily GitHub trending business-opportunity report.")
    parser.add_argument("--limit", type=int, help="research at most N new repos (to test cheaply)")
    args = parser.parse_args()

    # Libraries stay at WARNING (quiet); our own loggers ("research_agent...") show INFO progress.
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.INFO)

    from agent.researcher import make_researcher  # imported here so `--help` works without AWS credentials

    day = date.today().isoformat()
    run(make_researcher(), db_path=DB_PATH, report_path=REPORTS_DIR / f"{day}.pdf", day=day, limit=args.limit)


if __name__ == "__main__":
    main()
