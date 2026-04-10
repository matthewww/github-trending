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
ARCHIVE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "dashboard", "data", "archive")
)
ARCHIVE_INDEX_PATH = os.path.join(ARCHIVE_DIR, "index.json")


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
        .select("repo_name, purpose, category, key_themes, notable_because")
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
            "notable_because": insight.get("notable_because") or None,
        })

    for period in by_period:
        by_period[period].sort(key=lambda x: x["rank"] or 99)

    return dict(by_period)


def get_latest_digest(db: SupabaseClient) -> dict | None:
    resp = (
        db.client.table("weekly_digest")
        .select("week_start, week_end, headline, digest, top_categories, top_repos, emerging_themes, data_quality_pct, confidence_label")
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


def get_latest_clusters(db: SupabaseClient) -> list[dict]:
    """Most recent cluster run with repo assignments and 2D coords."""
    clusters_resp = (
        db.client.table("clusters")
        .select("id, label, description, size, run_date")
        .order("run_date", desc=True)
        .limit(50)
        .execute()
    )
    rows = clusters_resp.data or []
    if not rows:
        return []

    latest_date = rows[0]["run_date"]
    this_run = [r for r in rows if r["run_date"] == latest_date]
    cluster_ids = [r["id"] for r in this_run]

    map_resp = (
        db.client.table("repo_cluster_map")
        .select("repo_name, cluster_id, umap_x, umap_y")
        .in_("cluster_id", cluster_ids)
        .eq("run_date", latest_date)
        .execute()
    )
    map_rows = map_resp.data or []

    # Enrich scatter points with total_stars for bubble chart support
    scatter_repo_names = [m["repo_name"] for m in map_rows]
    stars_map: dict[str, int] = {}
    if scatter_repo_names:
        stars_resp = (
            db.client.table("trending_snapshots")
            .select("repo_name, total_stars")
            .in_("repo_name", scatter_repo_names)
            .order("collected_date", desc=True)
            .execute()
        )
        # Use most recent total_stars per repo (rows ordered newest first)
        for r in (stars_resp.data or []):
            if r["repo_name"] not in stars_map:
                stars_map[r["repo_name"]] = r.get("total_stars") or 0

    by_cluster: dict[int, list] = {r["id"]: [] for r in this_run}
    scatter = []
    for m in map_rows:
        by_cluster[m["cluster_id"]].append(m["repo_name"])
        scatter.append({
            "repo_name": m["repo_name"],
            "cluster_id": m["cluster_id"],
            "x": m["umap_x"],
            "y": m["umap_y"],
            "total_stars": stars_map.get(m["repo_name"], 0),
        })

    result = []
    for c in sorted(this_run, key=lambda x: x["size"] or 0, reverse=True):
        result.append({
            "id": c["id"],
            "label": c["label"],
            "description": c["description"],
            "size": c["size"],
            "repos": by_cluster.get(c["id"], []),
        })

    return {"run_date": latest_date, "clusters": result, "scatter": scatter}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export Supabase data to a static JSON snapshot")
    parser.add_argument("--no-archive", action="store_true",
                        help="Skip writing the dated archive file (use for daily runs)")
    args = parser.parse_args()

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
    clusters = get_latest_clusters(db)

    snapshot = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of_date": as_of_date,
        "today": today,
        "digest": digest,
        "history": history,
        "stats": stats,
        "clusters": clusters,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)

    if not args.no_archive:
        # Write dated archive copy (weekly runs only) — slim: no history or stats
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_path = os.path.join(ARCHIVE_DIR, f"{as_of_date}.json")
        archive_snapshot = {k: v for k, v in snapshot.items() if k != "stats"}
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(archive_snapshot, f, indent=2, default=str)

        # Update archive index (sorted newest-first, deduped)
        existing = []
        if os.path.exists(ARCHIVE_INDEX_PATH):
            with open(ARCHIVE_INDEX_PATH, encoding="utf-8") as f:
                existing = json.load(f)
        dates = sorted(set(existing) | {as_of_date}, reverse=True)
        with open(ARCHIVE_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(dates, f, indent=2)

    print(f"Written to {OUTPUT_PATH}")
    for period, repos in today.items():
        print(f"  {period}: {len(repos)} repos")
    print(f"  history: {len(history)} days")
    n_clusters = len((clusters or {}).get("clusters", []))
    print(f"  clusters: {n_clusters}")
    print(f"  stats: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
