#!/usr/bin/env python3
"""Backfill stable cluster identity over historical clustering runs.

Walks historical `clusters` runs in date order, applies the same matching
rule as the live identity layer (membership Jaccard >= 0.4, with the
centroid-cosine fallback for drifted clusters), and populates
`cluster_registry`, `cluster_weeks`, `clusters.cluster_key` and — for the
most recent run — `repo_cluster_map.stable_cluster_key`.

Idempotent: refuses to run if identity data already exists unless --force,
which clears registry/weeks and rebuilds from scratch.

Usage:
  python src/backfill_cluster_identity.py --dry-run   # preview, no writes
  python src/backfill_cluster_identity.py             # first backfill
  python src/backfill_cluster_identity.py --force     # rebuild
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np
from dotenv import load_dotenv

from supabase_client import SupabaseClient

load_dotenv()

JACCARD_MATCH_THRESHOLD = 0.4
JACCARD_MIN_FALLBACK = 0.2
CENTROID_MATCH_THRESHOLD = 0.85
RETIRE_AFTER_DAYS = 21


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


def slugify(label: str, taken: set) -> str:
    base = "".join(c if c.isalnum() else "-" for c in (label or "").lower())
    base = "-".join(p for p in base.split("-") if p)[:48] or "cluster"
    key, n = base, 2
    while key in taken:
        key = f"{base}-{n}"
        n += 1
    return key


def parse_vec(raw) -> np.ndarray | None:
    if raw is None:
        return None
    return np.array(json.loads(raw) if isinstance(raw, str) else raw, dtype=np.float32)


def fetch_history(db: SupabaseClient) -> tuple[dict, dict]:
    """Return (runs, centroids): runs = {run_date: {cluster_id: {label, description, size, members}}}."""
    cluster_rows = db.fetch_all(
        db.client.table("clusters")
        .select("id, run_date, label, description, size, centroid")
        .order("run_date")
        .order("id")
    )
    map_rows = db.fetch_all(
        db.client.table("repo_cluster_map")
        .select("repo_name, cluster_id, run_date")
    )

    centroids = {r["id"]: parse_vec(r.get("centroid")) for r in cluster_rows}
    runs: dict[str, dict] = {}
    for r in cluster_rows:
        runs.setdefault(r["run_date"], {})[r["id"]] = {
            "label": r.get("label") or "Unnamed Cluster",
            "description": r.get("description"),
            "size": r.get("size") or 0,
            "members": set(),
        }
    for m in map_rows:
        run = runs.get(m["run_date"])
        if run and m["cluster_id"] in run:
            run[m["cluster_id"]]["members"].add(m["repo_name"])
    return runs, centroids


def match_key(
    members: set,
    centroid: np.ndarray | None,
    prev: list[dict],
    used: set,
) -> str | None:
    best_j, best = 0.0, None
    for p in prev:
        if p["key"] in used:
            continue
        jac = jaccard(members, p["members"])
        if jac > best_j:
            best_j, best = jac, p
    if best is not None and best_j >= JACCARD_MATCH_THRESHOLD:
        return best["key"]
    if best is not None and best_j >= JACCARD_MIN_FALLBACK and centroid is not None and best["centroid"] is not None:
        if cosine_similarity(centroid, best["centroid"]) >= CENTROID_MATCH_THRESHOLD:
            return best["key"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Backfill cluster identity history")
    parser.add_argument("--force", action="store_true",
                        help="Clear existing identity data and rebuild")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute and print the plan without writing anything")
    args = parser.parse_args()

    db = SupabaseClient()

    existing = db.client.table("cluster_registry").select("cluster_key").limit(1).execute()
    if (existing.data or []) and not args.force:
        print("cluster_registry is not empty — use --force to rebuild identity from scratch")
        return 1

    if args.force and not args.dry_run:
        old_keys = [r["cluster_key"] for r in db.fetch_all(
            db.client.table("cluster_registry").select("cluster_key"))]
        if old_keys:
            db.client.table("cluster_weeks").delete().in_("cluster_key", old_keys).execute()
            db.client.table("cluster_registry").delete().in_("cluster_key", old_keys).execute()
        keyed = db.fetch_all(
            db.client.table("clusters").select("id").not_.is_("cluster_key", "null"))
        for r in keyed:
            db.client.table("clusters").update({"cluster_key": None}).eq("id", r["id"]).execute()
        print(f"Cleared {len(old_keys)} registry keys and {len(keyed)} cluster key links")

    print("Loading clustering history...")
    runs, centroids = fetch_history(db)
    run_dates = sorted(runs.keys())
    if not run_dates:
        print("No clustering runs found — nothing to backfill")
        return 0
    print(f"  {len(run_dates)} runs, {sum(len(v) for v in runs.values())} clusters total")

    registry: dict[str, dict] = {}
    taken: set[str] = set()
    week_rows: list[dict] = []
    cluster_key_by_id: dict[int, str] = {}
    prev: list[dict] = []
    new_counts = []

    for run_date in run_dates:
        used: set[str] = set()
        assignments: dict[int, str] = {}
        n_new = 0
        for cid, info in runs[run_date].items():
            members = info["members"]
            centroid = centroids.get(cid)
            key = match_key(members, centroid, prev, used) if prev else None
            if key:
                used.add(key)
                registry[key]["last_seen"] = run_date
                registry[key]["weeks_seen"] += 1
            else:
                key = slugify(info["label"], taken)
                taken.add(key)
                used.add(key)
                n_new += 1
                registry[key] = {
                    "cluster_key": key,
                    "label": info["label"],
                    "description": info["description"],
                    "first_seen": run_date,
                    "last_seen": run_date,
                    "weeks_seen": 1,
                    "status": "active",
                }
            assignments[cid] = key
            cluster_key_by_id[cid] = key
            if members:
                week_rows.append({"cluster_key": key, "week": run_date, "size": len(members)})
        prev = [
            {"key": assignments[cid], "members": runs[run_date][cid]["members"],
             "centroid": centroids.get(cid)}
            for cid in runs[run_date]
        ]
        new_counts.append((run_date, len(assignments), n_new))
        print(f"  {run_date}: {len(assignments)} clusters, {n_new} new")

    retire_cutoff = (date.today() - timedelta(days=RETIRE_AFTER_DAYS)).isoformat()
    retired = [
        key for key, row in registry.items()
        if row["status"] == "active" and (row["last_seen"] or "") <= retire_cutoff
    ]

    print(f"\nPlan: {len(registry)} stable clusters, {len(week_rows)} weekly size rows, "
          f"{len(retired)} to retire")

    if args.dry_run:
        print("\nTop clusters by weeks seen:")
        for row in sorted(registry.values(), key=lambda r: -r["weeks_seen"])[:15]:
            print(f"  {row['cluster_key']:<40} {row['label']:<32} "
                  f"{row['weeks_seen']}w  {row['first_seen']} -> {row['last_seen']}")
        print("\n--dry-run: no writes performed")
        return 0

    print("Writing registry...")
    rows = list(registry.values())
    for i in range(0, len(rows), 500):
        db.client.table("cluster_registry").upsert(rows[i:i + 500]).execute()

    print(f"Writing {len(week_rows)} cluster_weeks rows...")
    for i in range(0, len(week_rows), 500):
        db.client.table("cluster_weeks").upsert(week_rows[i:i + 500]).execute()

    print(f"Linking {len(cluster_key_by_id)} clusters to keys...")
    done = 0
    for cid, key in cluster_key_by_id.items():
        db.client.table("clusters").update({"cluster_key": key}).eq("id", cid).execute()
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{len(cluster_key_by_id)}")

    latest_date = run_dates[-1]
    latest_links = {cid: key for cid, key in cluster_key_by_id.items() if cid in runs[latest_date]}
    print(f"Setting stable keys on {latest_date} repo_cluster_map rows...")
    for cid, key in latest_links.items():
        db.client.table("repo_cluster_map").update({"stable_cluster_key": key}) \
            .eq("run_date", latest_date).eq("cluster_id", cid).execute()

    for key in retired:
        db.client.table("cluster_registry").update({"status": "retired"}).eq("cluster_key", key).execute()

    print(f"\nBackfill complete: {len(registry)} clusters, {len(retired)} retired. "
          f"Next live run will inherit from {latest_date}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
