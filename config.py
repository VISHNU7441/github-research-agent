"""Central settings for the GitHub research agent.

Every other module imports from here, so the model, limits and paths
are changed in one place.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")   # always this project's .env, whatever folder you run from

DATA_DIR = BASE_DIR / "data"          # SQLite history (gitignored)
REPORTS_DIR = BASE_DIR / "reports"    # daily PDFs (gitignored)
DB_PATH = DATA_DIR / "history.db"

# --- Amazon Bedrock ---
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")
MODEL_ID = "global.amazon.nova-2-lite-v1:0"
TEMPERATURE = 0.2                      # low = steadier, less "creative" analysis

# --- GitHub ---
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_API = "https://api.github.com"
TRENDING_URL = "https://github.com/trending"

# --- Web search ---
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]

# --- Limits that keep tokens (and credits) under control ---
MAX_README_CHARS = 8_000
MAX_FILE_CHARS = 4_000
MAX_ISSUES = 10
RECURSION_LIMIT = 25    # LangGraph steps per repo: each model call and each tool round is 1 step
HTTP_TIMEOUT = 20       # seconds before a GitHub/trending request gives up
MAX_SEARCH_RESULTS = 5   # web results per search (more results = more tokens)

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)


if __name__ == "__main__":
    print(f"Model:   {MODEL_ID} ({AWS_REGION})")
    print(f"GitHub:  {GITHUB_TOKEN[:11]}***")
    print(f"Tavily:  {TAVILY_API_KEY[:5]}***")
    print(f"DB:      {DB_PATH}")
    print(f"Reports: {REPORTS_DIR}")
