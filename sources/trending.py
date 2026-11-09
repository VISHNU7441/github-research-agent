"""Scrape github.com/trending and return the day's trending repositories.

GitHub has no API for the trending page, so we download the HTML and
pick the fields out of it with BeautifulSoup.
"""
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, TRENDING_URL


@dataclass
class TrendingRepo:
    rank: int            # position on the page (1 = top)
    full_name: str       # "owner/repo"
    url: str
    description: str
    language: str
    stars: int           # total stars
    forks: int
    stars_today: int     # stars gained in the selected period


def _to_int(text: str) -> int:
    """Keep only the digits: '2,373 stars today' -> 2373, '' -> 0."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def fetch_trending(since: str = "daily", language: str = "") -> list[TrendingRepo]:
    """Download the trending page and parse every repository on it."""
    url = f"{TRENDING_URL}/{language}" if language else TRENDING_URL
    response = requests.get(
        url,
        params={"since": since},  # becomes ?since=daily
        headers={"User-Agent": "github-research-agent (learning project)"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()  # turn 4xx/5xx into an exception instead of parsing an error page
    return parse_trending(response.text)


def parse_trending(html: str) -> list[TrendingRepo]:
    """Turn the trending page HTML into TrendingRepo objects."""
    soup = BeautifulSoup(html, "html.parser")
    repos = []

    for rank, article in enumerate(soup.select("article.Box-row"), start=1):
        link = article.select_one("h2 a")
        if link is None:  # a row without a repo link: skip it instead of crashing
            continue
        full_name = link["href"].strip("/")  # "/owner/repo" -> "owner/repo"

        # these can be missing (e.g. repos without a description or language)
        desc = article.select_one("p")
        lang = article.select_one('[itemprop="programmingLanguage"]')
        stars = article.select_one('a[href$="/stargazers"]')
        forks = article.select_one('a[href$="/forks"]')
        today = article.select_one("span.float-sm-right")

        repos.append(TrendingRepo(
            rank=rank,
            full_name=full_name,
            url=f"https://github.com/{full_name}",
            description=desc.get_text(strip=True) if desc else "",
            language=lang.get_text(strip=True) if lang else "",
            stars=_to_int(stars.get_text()) if stars else 0,
            forks=_to_int(forks.get_text()) if forks else 0,
            stars_today=_to_int(today.get_text()) if today else 0,
        ))

    if not repos:
        raise RuntimeError("No repos found: GitHub may have changed the trending page layout.")
    return repos


if __name__ == "__main__":
    repos = fetch_trending()
    print(f"Found {len(repos)} trending repos\n")
    for r in repos:
        print(f"{r.rank:>2}. {r.full_name:<45} {r.language or '-':<12} "
              f"★{r.stars:>8,}  +{r.stars_today:,} today")
        print(f"    {r.description[:90]}")
