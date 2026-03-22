#!/usr/bin/env python3
"""Weekly LLM-powered enrichment of trending repos with purpose/creator insights."""

import os
import sys
import json
import time
import base64
import argparse
import requests
from dotenv import load_dotenv
from openai import OpenAI
from supabase_client import SupabaseClient

load_dotenv()

GITHUB_API = "https://api.github.com"
MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o-mini"
README_MAX_CHARS = 3000
REQUEST_DELAY = 5  # seconds between LLM calls to stay within free tier


def get_headers():
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_readme(owner: str, repo: str) -> str | None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        if r.status_code == 200:
            content = r.json().get("content", "")
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
            return decoded[:README_MAX_CHARS]
        return None
    except Exception as e:
        print(f"  README fetch failed for {owner}/{repo}: {e}")
        return None


def fetch_repo_meta(owner: str, repo: str) -> dict:
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                "description": data.get("description", ""),
                "topics": data.get("topics", []),
                "owner_type": data.get("owner", {}).get("type", ""),
            }
    except Exception:
        pass
    return {}


def analyze_with_llm(
    client: OpenAI,
    repo_name: str,
    description: str,
    readme: str,
    topics: list,
    prior_repos: list[str],
) -> dict | None:
    prior_context = (
        f"This owner has previously appeared in GitHub trending with: {', '.join(prior_repos)}."
        if prior_repos
        else "This is the first time this owner has appeared in our trending data."
    )

    prompt = f"""Analyze this GitHub repository and return a JSON object with the fields below.

Repository: {repo_name}
Description: {description or "(none)"}
Topics: {', '.join(topics) if topics else "(none)"}
Creator context: {prior_context}

README (truncated):
---
{readme or "(no README available)"}
---

Return ONLY valid JSON with these exact fields:
{{
  "purpose": "one sentence describing what this repo does",
  "category": "one of: AI/ML, Developer Tools, Security, Web Framework, Data Science, Infrastructure, Education, Game/Creative, Productivity, Other",
  "creator_name": "the owner name from the repo path",
  "creator_type": "one of: individual, startup, big_tech, academic, open_source_org",
  "creator_description": "1-2 sentences about the creator based on available signals",
  "target_audience": "who this repo is primarily for",
  "key_themes": ["array", "of", "3-6", "keyword", "themes"]
}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a technical analyst. Always respond with valid JSON only, no markdown fences.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=500,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error for {repo_name}: {e}")
        return None
    except Exception as e:
        print(f"  LLM call failed for {repo_name}: {e}")
        return None


def get_unanalyzed_repos_direct(db: SupabaseClient) -> list[str]:
    """Fetch repos from last 7 days not in repo_insights via two queries."""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=7)).isoformat()

    recent = (
        db.client.table("repositories")
        .select("repo_name")
        .gte("collected_date", cutoff)
        .execute()
    )
    all_recent = {r["repo_name"] for r in (recent.data or [])}

    analyzed = db.client.table("repo_insights").select("repo_name").execute()
    already_done = {r["repo_name"] for r in (analyzed.data or [])}

    return list(all_recent - already_done)


def get_prior_repos_by_owner(db: SupabaseClient, owner: str) -> list[str]:
    """Find other repos in repo_insights from the same owner."""
    response = (
        db.client.table("repo_insights")
        .select("repo_name")
        .like("repo_name", f"{owner}/%")
        .execute()
    )
    return [r["repo_name"] for r in (response.data or [])]


def upsert_insight(db: SupabaseClient, repo_name: str, insight: dict, model: str):
    from datetime import datetime

    record = {
        "repo_name": repo_name,
        "purpose": insight.get("purpose"),
        "category": insight.get("category"),
        "creator_name": insight.get("creator_name"),
        "creator_type": insight.get("creator_type"),
        "creator_description": insight.get("creator_description"),
        "creator_prior_repos": insight.get("creator_prior_repos", []),
        "target_audience": insight.get("target_audience"),
        "key_themes": insight.get("key_themes", []),
        "model_used": model,
        "analyzed_at": datetime.utcnow().isoformat(),
    }
    db.client.table("repo_insights").upsert(record, on_conflict="repo_name").execute()


def reconcile_prior_repos(db: SupabaseClient, dry_run: bool = False):
    """Update creator_prior_repos for all existing insights based on current table state."""
    all_insights = db.client.table("repo_insights").select("repo_name").execute()
    all_repo_names = [r["repo_name"] for r in (all_insights.data or [])]

    # Group by owner
    by_owner: dict[str, list[str]] = {}
    for repo_name in all_repo_names:
        parts = repo_name.split("/", 1)
        if len(parts) == 2:
            owner = parts[0]
            by_owner.setdefault(owner, []).append(repo_name)

    updated = 0
    for owner, repos in by_owner.items():
        if len(repos) < 2:
            continue  # Only matters when owner has multiple repos
        for repo_name in repos:
            prior = [r for r in repos if r != repo_name]
            if dry_run:
                print(f"  [dry-run] would set {repo_name} prior_repos → {prior}")
            else:
                db.client.table("repo_insights").update(
                    {"creator_prior_repos": prior}
                ).eq("repo_name", repo_name).execute()
            updated += 1

    if updated:
        print(f"Reconciled creator_prior_repos for {updated} repo(s) across {sum(1 for v in by_owner.values() if len(v) > 1)} owner(s)")


def main():
    parser = argparse.ArgumentParser(description="Analyze trending repos with LLM insights")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch README/meta but skip LLM call and DB write")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of repos to process (useful for testing)")
    args = parser.parse_args()

    print("Starting weekly repo analysis...")
    if args.dry_run:
        print("DRY RUN — LLM calls and DB writes skipped")

    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("Warning: GITHUB_TOKEN not set — GitHub API rate limit is 60 req/hr")

    llm_token = os.environ.get("GH_MODELS_TOKEN") or github_token
    if not llm_token:
        print("Error: Neither GH_MODELS_TOKEN nor GITHUB_TOKEN is set — LLM calls will fail")
    elif not os.environ.get("GH_MODELS_TOKEN"):
        print("Warning: GH_MODELS_TOKEN not set — falling back to GITHUB_TOKEN (requires models permission)")

    llm_client = OpenAI(
        base_url=MODELS_ENDPOINT,
        api_key=llm_token or "no-key",
    )

    db = SupabaseClient()

    repos = get_unanalyzed_repos_direct(db)
    if args.limit:
        repos = repos[:args.limit]
    print(f"Found {len(repos)} repos to analyze")

    if not repos:
        print("Nothing to do.")
        return 0

    success, failed = 0, 0

    for i, repo_name in enumerate(repos, 1):
        parts = repo_name.split("/", 1)
        if len(parts) != 2:
            print(f"  Skipping malformed repo name: {repo_name}")
            continue

        owner, repo = parts
        print(f"[{i}/{len(repos)}] Analyzing {repo_name}...")

        meta = fetch_repo_meta(owner, repo)
        readme = fetch_readme(owner, repo)
        prior_repos = get_prior_repos_by_owner(db, owner)

        # Exclude the current repo from prior list
        prior_repos = [r for r in prior_repos if r != repo_name]
        if prior_repos:
            print(f"  Owner has {len(prior_repos)} prior insight(s): {prior_repos}")

        if args.dry_run:
            print(f"  readme: {len(readme or '')} chars, meta: {meta}, prior: {prior_repos}")
            continue

        insight = analyze_with_llm(
            llm_client,
            repo_name,
            meta.get("description", ""),
            readme,
            meta.get("topics", []),
            prior_repos,
        )

        if insight:
            insight["creator_prior_repos"] = prior_repos
            upsert_insight(db, repo_name, insight, MODEL)
            print(f"  ✓ {insight.get('category')} — {insight.get('purpose', '')[:80]}")
            success += 1
        else:
            print(f"  ✗ Failed to get insight")
            failed += 1

        if i < len(repos):
            time.sleep(REQUEST_DELAY)

    print(f"\nDone. {success} succeeded, {failed} failed.")

    print("\nReconciling creator connections...")
    reconcile_prior_repos(db, dry_run=args.dry_run)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
