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
SERIES_DAYS = 90
OUTPUT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "dashboard", "data", "snapshot.json")
)
HISTORY_OUTPUT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "dashboard", "data", "history.json")
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


def get_repo_meta_all(db: SupabaseClient) -> dict[str, dict]:
    """All-time per-repo stats computed from the full daily snapshot history.

    Returns {repo_name: {first_seen, last_seen, days_trended, weeks_trended,
    best_day_stars, latest_total_stars}}.
    """
    rows = db.fetch_all(
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date, stars_in_period, total_stars")
        .eq("since_period", "daily")
        .order("collected_date")
    )

    agg: dict[str, dict] = {}
    for r in rows:
        name = r["repo_name"]
        d = r["collected_date"]
        stars = r.get("stars_in_period") or 0
        a = agg.get(name)
        if a is None:
            agg[name] = {
                "first_seen": d,
                "last_seen": d,
                "days_trended": 1,
                "dates": [d],
                "weeks": {_week_start(d)},
                "best_day_stars": stars,
                "latest_total_stars": r.get("total_stars") or 0,
            }
            continue
        a["last_seen"] = max(a["last_seen"], d)
        a["days_trended"] += 1
        a["dates"].append(d)
        a["weeks"].add(_week_start(d))
        a["best_day_stars"] = max(a["best_day_stars"], stars)
        a["latest_total_stars"] = r.get("total_stars") or a["latest_total_stars"]

    meta = {}
    for name, a in agg.items():
        dates = sorted(set(a["dates"]))
        best_run = run = 1
        for i in range(1, len(dates)):
            run = run + 1 if (date.fromisoformat(dates[i]) - date.fromisoformat(dates[i - 1])).days == 1 else 1
            best_run = max(best_run, run)
        meta[name] = {
            "first_seen": a["first_seen"],
            "last_seen": a["last_seen"],
            "days_trended": a["days_trended"],
            "weeks_trended": len(a["weeks"]),
            "longest_streak": best_run,
            "best_day_stars": a["best_day_stars"],
            "latest_total_stars": a["latest_total_stars"],
        }
    return meta


def _week_start(iso_date: str) -> str:
    from datetime import datetime
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return (d - timedelta(days=d.weekday())).isoformat()


def get_full_daily_history(db: SupabaseClient, category_map: dict[str, str], lang_map: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Every collected day + ISO-week buckets, aggregated, for long-horizon charts.

    Returns (daily, weekly):
      daily  = [{date, repo_count, top_repos, category_counts, language_counts}]
      weekly = [{week, repo_count, category_counts, language_counts, top_repos}]
    """
    rows = db.fetch_all(
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date, stars_in_period")
        .eq("since_period", "daily")
        .order("collected_date")
    )

    by_date: dict[str, list] = defaultdict(list)
    for r in rows:
        by_date[r["collected_date"]].append(r)

    daily = []
    weekly_agg: dict[str, dict] = {}
    for d, day_rows in sorted(by_date.items()):
        top_repos = sorted(day_rows, key=lambda x: x.get("stars_in_period") or 0, reverse=True)[:5]
        cat_counts = Counter(category_map.get(r["repo_name"], "Unknown") for r in day_rows)
        lang_counts = Counter(
            lang_map.get(r["repo_name"])
            for r in day_rows
            if lang_map.get(r["repo_name"])
        )
        daily.append({
            "date": d,
            "repo_count": len(day_rows),
            "top_repos": [r["repo_name"] for r in top_repos],
            "category_counts": dict(cat_counts.most_common(10)),
            "language_counts": dict(lang_counts.most_common(10)),
        })

        w = _week_start(d)
        wk = weekly_agg.setdefault(w, {
            "repos": set(),
            "top_repos": {},
            "category_counts": Counter(),
            "language_counts": Counter(),
        })
        wk["repos"].update(r["repo_name"] for r in day_rows)
        for r in top_repos:
            stars = r.get("stars_in_period") or 0
            if wk["top_repos"].get(r["repo_name"], 0) < stars:
                wk["top_repos"][r["repo_name"]] = stars
        wk["category_counts"].update(cat_counts)
        wk["language_counts"].update(lang_counts)

    weekly = []
    for w, wk in sorted(weekly_agg.items()):
        top = sorted(wk["top_repos"].items(), key=lambda x: x[1], reverse=True)[:5]
        weekly.append({
            "week": w,
            "repo_count": len(wk["repos"]),
            "top_repos": [{"repo_name": n, "max_stars_today": s} for n, s in top],
            "category_counts": dict(wk["category_counts"].most_common(10)),
            "language_counts": dict(wk["language_counts"].most_common(10)),
        })

    return daily, weekly


def get_trending_series(db: SupabaseClient, repo_names: list[str], days: int = SERIES_DAYS) -> dict[str, list]:
    """Sparse (date, total_stars) series per repo for growth sparklines."""
    if not repo_names:
        return {}
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = db.fetch_all(
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date, total_stars")
        .in_("repo_name", repo_names)
        .eq("since_period", "daily")
        .gte("collected_date", cutoff)
        .order("collected_date")
    )
    series: dict[str, list] = defaultdict(list)
    for r in rows:
        total = r.get("total_stars")
        if total is not None:
            series[r["repo_name"]].append([r["collected_date"], total])
    return dict(series)


def get_category_language_maps(db: SupabaseClient) -> tuple[dict[str, str], dict[str, str]]:
    insights_resp = db.client.table("repo_insights").select("repo_name, category").execute()
    category_map = {i["repo_name"]: i.get("category", "Unknown") for i in (insights_resp.data or [])}
    repos_rows = db.fetch_all(db.client.table("repos").select("repo_name, language"))
    lang_map = {r["repo_name"]: r.get("language") for r in repos_rows}
    return category_map, lang_map


def get_today_snapshots(db: SupabaseClient, as_of_date: str, repo_meta: dict[str, dict] | None = None) -> dict:
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
            "first_seen": (repo_meta or {}).get(name, {}).get("first_seen"),
            "days_trended": (repo_meta or {}).get(name, {}).get("days_trended"),
            "weeks_trended": (repo_meta or {}).get(name, {}).get("weeks_trended"),
        })

    for period in by_period:
        by_period[period].sort(key=lambda x: x["rank"] or 99)

    return dict(by_period)


def get_latest_digest(db: SupabaseClient, target_date: date | None = None) -> dict | None:
    """Digest for the week containing target_date, falling back to the latest available."""
    if target_date:
        iso = target_date.isoformat()
        resp = (
            db.client.table("weekly_digest")
            .select("week_start, week_end, headline, digest, top_categories, top_repos, data_quality_pct, confidence_label")
            .lte("week_start", iso)
            .gte("week_end", iso)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]
    resp = (
        db.client.table("weekly_digest")
        .select("week_start, week_end, headline, digest, top_categories, top_repos, data_quality_pct, confidence_label")
        .order("week_start", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_history(db: SupabaseClient) -> list[dict]:
    """Last HISTORY_DAYS days of daily snapshots, aggregated by date."""
    cutoff = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()

    rows = db.fetch_all(
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date, stars_in_period")
        .eq("since_period", "daily")
        .gte("collected_date", cutoff)
        .order("collected_date", desc=True)
    )
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
    dates_rows = db.fetch_all(
        db.client.table("trending_snapshots")
        .select("collected_date")
        .eq("since_period", "daily")
    )
    dates = sorted({r["collected_date"] for r in dates_rows})

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

    map_rows = db.fetch_all(
        db.client.table("repo_cluster_map")
        .select("repo_name, cluster_id, umap_x, umap_y")
        .in_("cluster_id", cluster_ids)
        .eq("run_date", latest_date)
    )

    # Enrich scatter points with total_stars for bubble chart support
    scatter_repo_names = [m["repo_name"] for m in map_rows]
    stars_map: dict[str, int] = {}
    if scatter_repo_names:
        stars_rows = db.fetch_all(
            db.client.table("trending_snapshots")
            .select("repo_name, total_stars")
            .in_("repo_name", scatter_repo_names)
            .order("collected_date", desc=True)
        )
        # Use most recent total_stars per repo (rows ordered newest first)
        for r in stars_rows:
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
    parser.add_argument("--date", type=str, default=None,
                        help="Backfill: export as-of YYYY-MM-DD instead of the latest collected date")
    parser.add_argument("--digest-file", type=str, default=None,
                        help="Backfill: use digest JSON from file instead of the database")
    args = parser.parse_args()

    db = SupabaseClient()

    backfill_date = date.fromisoformat(args.date) if args.date else None
    as_of_date = backfill_date.isoformat() if backfill_date else get_latest_date(db)
    if not as_of_date:
        print("No data found in trending_snapshots")
        return 1

    print(f"Exporting snapshot as of {as_of_date}...")

    repo_meta = get_repo_meta_all(db)
    print(f"  repo meta computed for {len(repo_meta)} repos")

    today = get_today_snapshots(db, as_of_date, repo_meta)
    if not today and backfill_date:
        print(f"No trending snapshots found for {as_of_date} — nothing to archive")
        return 1
    if args.digest_file:
        with open(args.digest_file, encoding="utf-8") as f:
            digest = json.load(f)
    else:
        digest = get_latest_digest(db, backfill_date)
    history = get_history(db)
    stats = get_stats(db)
    clusters = get_latest_clusters(db)

    # Long-horizon export for the trends page
    category_map, lang_map = get_category_language_maps(db)
    daily_all, weekly_all = get_full_daily_history(db, category_map, lang_map)
    current_repos = sorted({r["repo_name"] for repos in today.values() for r in repos})
    series = get_trending_series(db, current_repos)
    history_export = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of_date": as_of_date,
        "first_date": stats.get("first_date"),
        "weeks": weekly_all,
        "daily": daily_all,
        "series": series,
        "meta": repo_meta,
        "categories": category_map,
        "languages": lang_map,
    }
    os.makedirs(os.path.dirname(HISTORY_OUTPUT_PATH), exist_ok=True)
    with open(HISTORY_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(history_export, f, default=str)
    print(f"  history: {len(daily_all)} days, {len(weekly_all)} weeks, {len(series)} series, {len(repo_meta)} repo metas")

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
