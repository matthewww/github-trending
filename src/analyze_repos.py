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
EMBED_MODEL = "all-MiniLM-L6-v2"
README_MAX_CHARS = 3000
REQUEST_DELAY = 5  # seconds between LLM calls to stay within free tier

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        print(f"Loading embedding model {EMBED_MODEL}...")
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def build_embed_text(insight: dict) -> str:
    themes = ", ".join(insight.get("key_themes") or [])
    parts = [
        insight.get("purpose") or "",
        f"Category: {insight.get('category') or ''}",
        f"Themes: {themes}" if themes else "",
        f"Audience: {insight.get('target_audience') or ''}",
    ]
    return ". ".join(p for p in parts if p).strip()


def embed_and_store(db: SupabaseClient, repo_name: str, insight: dict):
    from datetime import datetime
    try:
        text = build_embed_text(insight)
        if not text:
            return
        vec = get_embedder().encode(text, normalize_embeddings=True).tolist()
        db.client.table("embeddings").upsert(
            {
                "repo_name": repo_name,
                "embedding": vec,
                "source_text": text,
                "model_used": EMBED_MODEL,
                "generated_at": datetime.utcnow().isoformat(),
            },
            on_conflict="repo_name",
        ).execute()
    except Exception as e:
        print(f"  Embedding failed for {repo_name}: {e}")


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


def get_recent_insights_for_comparison(db: SupabaseClient, limit: int = 8) -> list[dict]:
    """Fetch recently analyzed repos to use as comparison context in the prompt."""
    resp = (
        db.client.table("repo_insights")
        .select("repo_name, purpose, category")
        .order("analyzed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def analyze_with_llm(
    client: OpenAI,
    repo_name: str,
    description: str,
    readme: str,
    topics: list,
    prior_repos: list[str],
    comparison_repos: list[dict] | None = None,
) -> dict | None:
    prior_context = (
        f"This owner has previously appeared in GitHub trending with: {', '.join(prior_repos)}."
        if prior_repos
        else "This is the first time this owner has appeared in our trending data."
    )

    comparison_context = ""
    if comparison_repos:
        lines = [f"- {r['repo_name']} ({r.get('category','?')}): {r.get('purpose','')}" for r in comparison_repos]
        comparison_context = (
            "\n\nOther repos currently/recently trending for comparison:\n"
            + "\n".join(lines)
        )

    prompt = f"""Analyze this GitHub repository and return a JSON object with the fields below.

Repository: {repo_name}
Description: {description or "(none)"}
Topics: {', '.join(topics) if topics else "(none)"}
Creator context: {prior_context}{comparison_context}

README (truncated):
---
{readme or "(no README available)"}
---

Return ONLY valid JSON with these exact fields:
{{
  "purpose": "one sentence describing what this repo does",
  "category": "one of: AI/ML, Developer Tools, Security, Web Framework, Data Science, Infrastructure, Education, Game/Creative, Productivity, Other",
  "owner_type": "one of: individual, startup, big_tech, academic, open_source_org",
  "owner_description": "1-2 sentences about the owner based on available signals",
  "target_audience": "who this repo is primarily for",
  "key_themes": ["array", "of", "3-6", "keyword", "themes"],
  "notable_because": "1-2 sentences on what makes this repo stand out compared to other tools in the same space, based on the comparison repos provided. If nothing clearly distinguishes it, say so honestly."
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


def get_unanalyzed_repos(db: SupabaseClient) -> list[str]:
    """Fetch repo names that have no entry in repo_insights yet."""
    response = db.client.table("repos_needing_insights").select("repo_name").execute()
    return [r["repo_name"] for r in (response.data or [])]


def get_repos_needing_notable_because(db: SupabaseClient, limit: int = 50) -> list[str]:
    """Fetch repos that have insights but are missing notable_because (for backfill)."""
    resp = (
        db.client.table("repo_insights")
        .select("repo_name")
        .is_("notable_because", "null")
        .order("analyzed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [r["repo_name"] for r in (resp.data or [])]


def get_prior_repos_by_owner(db: SupabaseClient, owner: str) -> list[str]:
    """Find other repos from the same owner already in the repos table."""
    response = (
        db.client.table("repos")
        .select("repo_name")
        .eq("owner_name", owner)
        .execute()
    )
    return [r["repo_name"] for r in (response.data or [])]


def upsert_owner(db: SupabaseClient, owner_name: str, owner_type: str, description: str):
    db.client.table("owners").upsert(
        {
            "owner_name": owner_name,
            "owner_type": owner_type,
            "description": description,
        },
        on_conflict="owner_name",
    ).execute()


def upsert_repo_topics(db: SupabaseClient, repo_name: str, topics: list[str]):
    if topics:
        db.client.table("repos").update({"topics": topics}).eq("repo_name", repo_name).execute()


def upsert_insight(db: SupabaseClient, repo_name: str, insight: dict, model: str):
    from datetime import datetime

    record = {
        "repo_name": repo_name,
        "purpose": insight.get("purpose"),
        "category": insight.get("category"),
        "target_audience": insight.get("target_audience"),
        "key_themes": insight.get("key_themes", []),
        "notable_because": insight.get("notable_because"),
        "model_used": model,
        "analyzed_at": datetime.utcnow().isoformat(),
    }
    db.client.table("repo_insights").upsert(record, on_conflict="repo_name").execute()


def main():
    parser = argparse.ArgumentParser(description="Analyze trending repos with LLM insights")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch README/meta but skip LLM call and DB write")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of repos to process (useful for testing)")
    parser.add_argument("--backfill-notable", action="store_true",
                        help="Re-analyze repos that are missing the notable_because field")
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

    if args.backfill_notable:
        backfill_limit = args.limit or 20
        repos = get_repos_needing_notable_because(db, limit=backfill_limit)
        print(f"Backfill mode: {len(repos)} repos missing notable_because")
    else:
        repos = get_unanalyzed_repos(db)
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
        prior_repos = [r for r in get_prior_repos_by_owner(db, owner) if r != repo_name]
        comparison_repos = get_recent_insights_for_comparison(db, limit=8)

        if prior_repos:
            print(f"  Owner has {len(prior_repos)} other trending repo(s): {prior_repos}")

        if args.dry_run:
            print(f"  readme: {len(readme or '')} chars, topics: {meta.get('topics', [])}, prior: {prior_repos}")
            continue

        insight = analyze_with_llm(
            llm_client,
            repo_name,
            meta.get("description", ""),
            readme,
            meta.get("topics", []),
            prior_repos,
            comparison_repos,
        )

        if insight:
            upsert_insight(db, repo_name, insight, MODEL)
            upsert_owner(db, owner, insight.get("owner_type", ""), insight.get("owner_description", ""))
            upsert_repo_topics(db, repo_name, meta.get("topics", []))
            embed_and_store(db, repo_name, insight)
            print(f"  ✓ {insight.get('category')} — {insight.get('purpose', '')[:80]}")
            success += 1
        else:
            print(f"  ✗ Failed to get insight")
            failed += 1

        if i < len(repos):
            time.sleep(REQUEST_DELAY)

    print(f"\nDone. {success} succeeded, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

