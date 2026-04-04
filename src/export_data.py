#!/usr/bin/env python3
"""Export Supabase data to a static JSON snapshot for the dashboard."""

import os
import sys
import json
from datetime import date, timedelta, datetime
from collections import defaultdict, Counter
from dotenv import load_dotenv
from supabase_client import SupabaseClient

load_dotenv()

HISTORY_DAYS = 30
OUTPUT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "dashboard", "data", "snapshot.json")
)


def get_latest_date(db: SupabaseClient) -> str | None:
    resp = (
        db.client.table("trending_snapshots")
        .select("collected_date")
        .eq("since_period", "daily")
        .order("collected_date", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0]["collected_date"] if resp.data else None


def get_today_snapshots(db: SupabaseClient, as_of_date: str) -> dict:
    """Trending snapshots for the given date (all periods), enriched with repo/owner/insight data."""
    snap_resp = (
        db.client.table("trending_snapshots")
        .select("repo_name, since_period, stars_in_period, total_stars, forks, rank")
        .eq("collected_date", as_of_date)
        .execute()
    )
    rows = snap_resp.data or []
    if not rows:
        return {}

    repo_names = list({r["repo_name"] for r in rows})

    repos_resp = (
        db.client.table("repos")
        .select("repo_name, description, language, owner_name")
        .in_("repo_name", repo_names)
        .execute()
    )
    repos_map = {r["repo_name"]: r for r in (repos_resp.data or [])}

    owner_names = list({r["owner_name"] for r in (repos_resp.data or []) if r.get("owner_name")})
    owners_resp = (
        db.client.table("owners")
        .select("owner_name, owner_type")
        .in_("owner_name", owner_names)
        .execute()
    )
    owners_map = {o["owner_name"]: o for o in (owners_resp.data or [])}

    insights_resp = (
        db.client.table("repo_insights")
        .select("repo_name, purpose, category, key_themes")
        .in_("repo_name", repo_names)
        .execute()
    )
    insights_map = {i["repo_name"]: i for i in (insights_resp.data or [])}

    by_period: dict[str, list] = defaultdict(list)
    for r in rows:
        name = r["repo_name"]
        repo = repos_map.get(name, {})
        owner_name = repo.get("owner_name", name.split("/")[0])
        owner = owners_map.get(owner_name, {})
        insight = insights_map.get(name, {})

        by_period[r["since_period"]].append({
            "repo_name": name,
            "description": repo.get("description"),
            "language": repo.get("language"),
            "owner_name": owner_name,
            "owner_type": owner.get("owner_type"),
            "stars_in_period": r["stars_in_period"],
            "total_stars": r["total_stars"],
            "forks": r["forks"],
            "rank": r["rank"],
            "purpose": insight.get("purpose"),
            "category": insight.get("category", "Unknown"),
            "key_themes": insight.get("key_themes") or [],
        })

    for period in by_period:
        by_period[period].sort(key=lambda x: x["rank"] or 99)

    return dict(by_period)


def get_latest_digest(db: SupabaseClient) -> dict | None:
    resp = (
        db.client.table("weekly_digest")
        .select("week_start, week_end, headline, digest, top_categories, top_repos, emerging_themes")
        .order("week_start", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_history(db: SupabaseClient) -> list[dict]:
    """Last HISTORY_DAYS days of daily snapshots, aggregated by date."""
    cutoff = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()

    snap_resp = (
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date, stars_in_period")
        .eq("since_period", "daily")
        .gte("collected_date", cutoff)
        .order("collected_date", desc=True)
        .execute()
    )
    rows = snap_resp.data or []
    if not rows:
        return []

    repo_names = list({r["repo_name"] for r in rows})

    insights_resp = (
        db.client.table("repo_insights")
        .select("repo_name, category")
        .in_("repo_name", repo_names)
        .execute()
    )
    category_map = {i["repo_name"]: i.get("category", "Unknown") for i in (insights_resp.data or [])}

    repos_resp = (
        db.client.table("repos")
        .select("repo_name, language")
        .in_("repo_name", repo_names)
        .execute()
    )
    lang_map = {r["repo_name"]: r.get("language") for r in (repos_resp.data or [])}

    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        by_date[r["collected_date"]].append(r)

    history = []
    for d, day_rows in sorted(by_date.items(), reverse=True):
        top_repos = sorted(day_rows, key=lambda x: x.get("stars_in_period") or 0, reverse=True)[:5]
        cat_counts = Counter(category_map.get(r["repo_name"], "Unknown") for r in day_rows)
        lang_counts = Counter(
            lang_map.get(r["repo_name"])
            for r in day_rows
            if lang_map.get(r["repo_name"])
        )
        history.append({
            "date": d,
            "repo_count": len(day_rows),
            "top_repos": [r["repo_name"] for r in top_repos],
            "category_counts": dict(cat_counts.most_common(8)),
            "language_counts": dict(lang_counts.most_common(8)),
        })

    return history


def get_stats(db: SupabaseClient) -> dict:
    repos_resp = db.client.table("repos").select("repo_name").execute()
    dates_resp = (
        db.client.table("trending_snapshots")
        .select("collected_date")
        .eq("since_period", "daily")
        .execute()
    )
    dates = sorted({r["collected_date"] for r in (dates_resp.data or [])})

    return {
        "total_repos": len(repos_resp.data or []),
        "days_tracked": len(dates),
        "first_date": dates[0] if dates else None,
        "latest_date": dates[-1] if dates else None,
    }


def main():
    db = SupabaseClient()

    as_of_date = get_latest_date(db)
    if not as_of_date:
        print("No data found in trending_snapshots")
        return 1

    print(f"Exporting snapshot as of {as_of_date}...")

    today = get_today_snapshots(db, as_of_date)
    digest = get_latest_digest(db)
    history = get_history(db)
    stats = get_stats(db)

    snapshot = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of_date": as_of_date,
        "today": today,
        "digest": digest,
        "history": history,
        "stats": stats,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)

    print(f"Written to {OUTPUT_PATH}")
    for period, repos in today.items():
        print(f"  {period}: {len(repos)} repos")
    print(f"  history: {len(history)} days")
    print(f"  stats: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
