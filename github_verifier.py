"""
GitHub Commit Verifier – MentorAgent
--------------------------------------
Verifies a GitHub commit URL or SHA exists in the user's repo.
Uses GitHub REST API with a personal access token.

Usage:
    from github_verifier import verify_commit

    result = verify_commit("https://github.com/owner/repo/commit/abc123def")
    if result["valid"]:
        print(result["message"])  # "✅ Commit verified: abc123 – Add threshold sweep"
    else:
        print(result["error"])

    # Also supports bare SHA or short SHA
    result = verify_commit("abc123def456", repo="owner/repo")

Environment variables:
    GITHUB_TOKEN   - Personal access token (repo:read or fine-grained Contents:Read)
    GITHUB_REPO    - Default repo, e.g. "siddharth/honestrag"

GitHub API rate limits:
    Unauthenticated: 60 req/hr — always set GITHUB_TOKEN to get 5000 req/hr
"""

import os
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_API_BASE = "https://api.github.com"


def _parse_commit_url(url: str) -> tuple[str | None, str | None]:
    """
    Parse a GitHub commit URL into (repo, sha).
    Handles formats:
        https://github.com/owner/repo/commit/abc123
        https://github.com/owner/repo/commit/abc123def456789...
    Returns (None, None) if not a valid commit URL.
    """
    pattern = r"github\.com/([^/]+/[^/]+)/commit/([0-9a-f]+)"
    match = re.search(pattern, url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def verify_commit(commit_ref: str, repo: str = None) -> dict:
    """
    Verify a commit exists on GitHub.

    Args:
        commit_ref: A full GitHub commit URL, full SHA, or short SHA
        repo: Repository in "owner/repo" format. Required if commit_ref is a bare SHA.
              Ignored if commit_ref is a full URL (repo parsed from URL).

    Returns:
        dict with keys:
            valid (bool)
            sha (str) – full 40-char SHA if valid
            short_sha (str) – first 7 chars
            message (str) – commit message if valid
            author (str) – commit author name
            date (str) – commit date ISO string
            url (str) – GitHub HTML URL
            error (str) – error description if not valid
    """
    target_repo = repo or GITHUB_REPO
    sha = commit_ref.strip()

    # If it looks like a URL, extract repo + SHA from it
    if "github.com" in sha:
        parsed_repo, parsed_sha = _parse_commit_url(sha)
        if parsed_sha:
            target_repo = parsed_repo
            sha = parsed_sha
        else:
            return {
                "valid": False,
                "error": f"Could not parse commit URL: {commit_ref}",
            }

    if not target_repo:
        return {
            "valid": False,
            "error": "No repo specified. Set GITHUB_REPO in .env or pass repo= argument.",
        }

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    else:
        print("[GitHub] Warning: GITHUB_TOKEN not set. Rate limit: 60 req/hr.")

    url = f"{GITHUB_API_BASE}/repos/{target_repo}/commits/{sha}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            full_sha = data["sha"]
            commit_msg = data["commit"]["message"].split("\n")[0]  # first line only
            author = data["commit"]["author"]["name"]
            date = data["commit"]["author"]["date"]
            html_url = data["html_url"]

            return {
                "valid": True,
                "sha": full_sha,
                "short_sha": full_sha[:7],
                "message": commit_msg,
                "author": author,
                "date": date,
                "url": html_url,
                "display": f"✅ Commit verified: `{full_sha[:7]}` – {commit_msg}",
            }

        elif resp.status_code == 404:
            return {
                "valid": False,
                "error": f"Commit `{sha[:7]}` not found in `{target_repo}`. Check the SHA or repo name.",
            }

        elif resp.status_code == 401:
            return {
                "valid": False,
                "error": "GitHub API: Unauthorized. Check GITHUB_TOKEN in .env.",
            }

        elif resp.status_code == 403:
            rate_limit = resp.headers.get("X-RateLimit-Remaining", "?")
            reset_at = resp.headers.get("X-RateLimit-Reset", "?")
            return {
                "valid": False,
                "error": f"GitHub API: Rate limited. Remaining: {rate_limit}. Resets at: {reset_at}.",
            }

        else:
            return {
                "valid": False,
                "error": f"GitHub API: Unexpected status {resp.status_code}: {resp.text[:200]}",
            }

    except requests.exceptions.ConnectionError:
        return {
            "valid": False,
            "error": "Network error — could not reach GitHub API.",
        }
    except requests.exceptions.Timeout:
        return {
            "valid": False,
            "error": "GitHub API request timed out.",
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Unexpected error: {e}",
        }


def get_recent_commits(repo: str = None, limit: int = 5) -> list[dict]:
    """
    Fetch the most recent commits for a repo.
    Useful for checking if any commit was made in the last 48 hours.

    Returns list of simplified commit dicts.
    """
    target_repo = repo or GITHUB_REPO
    if not target_repo:
        return []

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    url = f"{GITHUB_API_BASE}/repos/{target_repo}/commits"
    try:
        resp = requests.get(url, headers=headers, params={"per_page": limit}, timeout=10)
        resp.raise_for_status()
        commits = resp.json()
        return [
            {
                "sha": c["sha"],
                "short_sha": c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
                "url": c["html_url"],
            }
            for c in commits
        ]
    except Exception as e:
        print(f"[GitHub] Failed to fetch recent commits: {e}")
        return []


# ── CLI convenience ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Verify a GitHub commit")
    parser.add_argument("commit", help="Commit URL, full SHA, or short SHA")
    parser.add_argument("--repo", help="GitHub repo (owner/repo) — overrides GITHUB_REPO env var")
    parser.add_argument("--recent", type=int, metavar="N", help="List N recent commits instead")
    args = parser.parse_args()

    if args.recent:
        commits = get_recent_commits(repo=args.repo, limit=args.recent)
        print(json.dumps(commits, indent=2))
    else:
        result = verify_commit(args.commit, repo=args.repo)
        print(json.dumps(result, indent=2))
        if result["valid"]:
            print(f"\n{result['display']}")
