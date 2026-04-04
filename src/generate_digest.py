#!/usr/bin/env python3
"""Generate a weekly prose digest summarising GitHub trending activity."""

import os
import sys
import json
import argparse
from datetime import date, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from supabase_client import SupabaseClient

load_dotenv()

MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o-mini"


def get_week_bounds(reference_date: date = None) -> tuple[date, date]:
    """Return (monday, sunday) for the ISO week containing reference_date."""
    d = reference_date or date.today()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def fetch_week_repos(db: SupabaseClient, week_start: date, week_end: date) -> list[dict]:
    """Repos that trended this week (daily period), joined with their insights where available."""
    response = (
        db.client.table("trending_snapshots")
        .select("repo_name, total_stars, stars_in_period, collected_date")
        .eq("since_period", "daily")
        .gte("collected_date", week_start.isoformat())
        .lte("collected_date", week_end.isoformat())
        .execute()
    )
    rows = response.data or []

    # Aggregate per repo: max stars_in_period, days seen
    by_repo: dict[str, dict] = {}
    for r in rows:
        name = r["repo_name"]
        if name not in by_repo:
            by_repo[name] = {
                "repo_name": name,
                "max_stars_today": r["stars_in_period"] or 0,
                "total_stars": r["total_stars"],
                "days_seen": 1,
            }
        else:
            by_repo[name]["max_stars_today"] = max(
                by_repo[name]["max_stars_today"], r["stars_in_period"] or 0
            )
            by_repo[name]["days_seen"] += 1

    repos = sorted(by_repo.values(), key=lambda x: x["max_stars_today"], reverse=True)

    if not repos:
        return repos

    names = [r["repo_name"] for r in repos]

    # Enrich with repo metadata (language, owner)
    repos_resp = (
        db.client.table("repos")
        .select("repo_name, language, owner_name")
        .in_("repo_name", names)
        .execute()
    )
    repos_map = {r["repo_name"]: r for r in (repos_resp.data or [])}
    for r in repos:
        meta = repos_map.get(r["repo_name"], {})
        r["language"] = meta.get("language")
        r["owner_name"] = meta.get("owner_name", r["repo_name"].split("/")[0])

    # Enrich with insights
    insights_resp = (
        db.client.table("repo_insights")
        .select("repo_name, purpose, category, key_themes")
        .in_("repo_name", names)
        .execute()
    )
    insights_map = {i["repo_name"]: i for i in (insights_resp.data or [])}
    for r in repos:
        ins = insights_map.get(r["repo_name"], {})
        r["purpose"] = ins.get("purpose", "")
        r["category"] = ins.get("category", "Unknown")
        r["key_themes"] = ins.get("key_themes", [])

    return repos


def fetch_prev_week_repos(db: SupabaseClient, week_start: date) -> set[str]:
    """Repo names that appeared the previous week (daily period)."""
    prev_end = week_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    resp = (
        db.client.table("trending_snapshots")
        .select("repo_name")
        .eq("since_period", "daily")
        .gte("collected_date", prev_start.isoformat())
        .lte("collected_date", prev_end.isoformat())
        .execute()
    )
    return {r["repo_name"] for r in (resp.data or [])}


def fetch_category_history(db: SupabaseClient, week_start: date, weeks: int = 4) -> list[dict]:
    """Category counts per week for the last N weeks (including current)."""
    from collections import defaultdict
    start = week_start - timedelta(weeks=weeks - 1)
    end = week_start + timedelta(days=6)

    repos_resp = (
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date")
        .eq("since_period", "daily")
        .gte("collected_date", start.isoformat())
        .lte("collected_date", end.isoformat())
        .execute()
    )
    rows = repos_resp.data or []

    names = list({r["repo_name"] for r in rows})
    if not names:
        return []

    insights_resp = (
        db.client.table("repo_insights")
        .select("repo_name, category")
        .in_("repo_name", names)
        .execute()
    )
    category_map = {i["repo_name"]: i.get("category", "Unknown") for i in (insights_resp.data or [])}

    weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        d = date.fromisoformat(r["collected_date"])
        w = (d - timedelta(days=d.weekday())).isoformat()
        cat = category_map.get(r["repo_name"], "Unknown")
        weekly[w][cat] += 1

    return [{"week": w, "counts": dict(counts)} for w, counts in sorted(weekly.items())]


def build_context(
    week_start: date,
    week_end: date,
    this_week: list[dict],
    prev_week_names: set[str],
    category_history: list[dict],
) -> str:
    """Build a compact structured context string for the LLM prompt."""
    lines = []

    lines.append(f"## Week of {week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')}")
    lines.append(f"Total unique repos trending: {len(this_week)}")
    lines.append("")

    # Top repos by star velocity
    top5 = this_week[:5]
    lines.append("## Top repos by daily stars")
    for r in top5:
        purpose = f" — {r['purpose']}" if r.get("purpose") else ""
        lines.append(f"- {r['repo_name']} ({r['language'] or 'unknown lang'}): "
                     f"{r['max_stars_today']:,} stars/day{purpose}")
    lines.append("")

    # New vs returning
    new_repos = [r for r in this_week if r["repo_name"] not in prev_week_names]
    returning = [r for r in this_week if r["repo_name"] in prev_week_names]
    lines.append(f"## New this week: {len(new_repos)} | Returning from last week: {len(returning)}")
    lines.append("")

    # Category breakdown this week
    from collections import Counter
    cat_counts = Counter(r.get("category", "Unknown") for r in this_week)
    lines.append("## Category breakdown this week")
    for cat, count in cat_counts.most_common():
        lines.append(f"- {cat}: {count}")
    lines.append("")

    # Category shift vs last week
    if len(category_history) >= 2:
        prev_hist = category_history[-2]["counts"] if len(category_history) >= 2 else {}
        curr_hist = category_history[-1]["counts"] if category_history else {}
        lines.append("## Category shifts vs last week")
        all_cats = set(list(prev_hist.keys()) + list(curr_hist.keys()))
        for cat in sorted(all_cats):
            prev_n = prev_hist.get(cat, 0)
            curr_n = curr_hist.get(cat, 0)
            if prev_n != curr_n:
                arrow = "↑" if curr_n > prev_n else "↓"
                lines.append(f"- {cat}: {curr_n} ({arrow} from {prev_n})")
        lines.append("")

    # Creator connections — owners with multiple repos trending this week
    from collections import defaultdict
    repos_by_owner: dict[str, list[str]] = defaultdict(list)
    for r in this_week:
        repos_by_owner[r["owner_name"]].append(r["repo_name"])

    multi_repo_owners = {owner: repos for owner, repos in repos_by_owner.items() if len(repos) > 1}

    if multi_repo_owners:
        lines.append("## Creators with multiple trending repos")
        for owner, owner_repos in multi_repo_owners.items():
            lines.append(f"- {owner}: {', '.join(owner_repos)}")
        lines.append("")

    # Key themes this week (union of all key_themes)
    all_themes: list[str] = []
    for r in this_week:
        all_themes.extend(r.get("key_themes") or [])
    theme_counts = Counter(all_themes)
    if theme_counts:
        top_themes = [t for t, _ in theme_counts.most_common(10)]
        lines.append(f"## Most common themes this week")
        lines.append(", ".join(top_themes))
        lines.append("")

    # 4-week category trend summary
    if len(category_history) >= 3:
        lines.append("## 4-week category trend (oldest → newest)")
        for entry in category_history[-4:]:
            top = sorted(entry["counts"].items(), key=lambda x: x[1], reverse=True)[:3]
            top_str = ", ".join(f"{c}({n})" for c, n in top)
            lines.append(f"- {entry['week']}: {top_str}")
        lines.append("")

    return "\n".join(lines)


def generate_digest(llm_client: OpenAI, context: str, week_start: date) -> dict | None:
    prompt = f"""You are writing a weekly briefing on GitHub trending for a senior software developer.
Based on the data below, write an analytical, opinionated digest — like a sharp tech newsletter paragraph, not a list.

{context}

Return ONLY valid JSON with these exact fields:
{{
  "headline": "One punchy sentence capturing the defining story of this week",
  "digest": "400-500 word prose split into 3-4 paragraphs separated by \\n\\n. Cover: what dominated this week, any notable shifts in themes or language trends, standout repos and why they matter, creator patterns if notable, and what it signals about where software development is heading. Be analytical and specific — name repos, not just categories.",
  "top_categories": ["ordered list of top 4 categories this week"],
  "emerging_themes": ["3-5 themes that are new or notably surging this week"]
}}"""

    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a sharp technology analyst. Always respond with valid JSON only, no markdown fences.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=900,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}\nRaw: {raw[:200]}")
        return None
    except Exception as e:
        print(f"LLM call failed: {e}")
        return None


def upsert_digest(db: SupabaseClient, week_start: date, week_end: date, result: dict):
    from datetime import datetime
    record = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "headline": result.get("headline"),
        "digest": result.get("digest"),
        "top_categories": result.get("top_categories", []),
        "top_repos": result.get("top_repos", []),
        "emerging_themes": result.get("emerging_themes", []),
        "model_used": MODEL,
        "generated_at": datetime.utcnow().isoformat(),
    }
    db.client.table("weekly_digest").upsert(record, on_conflict="week_start").execute()


def main():
    parser = argparse.ArgumentParser(description="Generate weekly GitHub trending digest")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build context and print it, but skip LLM call and DB write")
    parser.add_argument("--week", type=str, default=None,
                        help="Override week as YYYY-MM-DD (any date within the desired week)")
    args = parser.parse_args()

    ref_date = date.fromisoformat(args.week) if args.week else date.today()
    week_start, week_end = get_week_bounds(ref_date)

    print(f"Generating digest for week {week_start} – {week_end}")
    if args.dry_run:
        print("DRY RUN — LLM call and DB write skipped")

    github_token = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not github_token and not args.dry_run:
        print("Error: GH_MODELS_TOKEN (or GITHUB_TOKEN) required for LLM calls")
        return 1

    db = SupabaseClient()

    this_week = fetch_week_repos(db, week_start, week_end)
    print(f"  {len(this_week)} repos trended this week")

    if not this_week:
        print("No data for this week — skipping digest generation")
        return 0

    prev_week_names = fetch_prev_week_repos(db, week_start)
    category_history = fetch_category_history(db, week_start)

    context = build_context(week_start, week_end, this_week, prev_week_names, category_history)

    print(f"\n--- Context ({len(context)} chars) ---\n{context}\n---\n")

    if args.dry_run:
        return 0

    llm_client = OpenAI(base_url=MODELS_ENDPOINT, api_key=github_token)

    print("Calling LLM...")
    result = generate_digest(llm_client, context, week_start)

    if not result:
        print("Failed to generate digest")
        return 1

    # Store top repos from our data (not LLM-generated — more reliable)
    result["top_repos"] = [r["repo_name"] for r in this_week[:5]]

    upsert_digest(db, week_start, week_end, result)
    print(f"\n✓ Digest saved for week of {week_start}")
    print(f"\nHeadline: {result.get('headline')}")
    print(f"\n{result.get('digest', '')[:300]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
