#!/usr/bin/env python3
"""Supabase client for storing trending repos."""

import os
from datetime import date
from typing import List, Dict
from supabase import create_client, Client


class SupabaseClient:
    def __init__(self, url: str = None, key: str = None):
        url = url or os.environ.get("SUPABASE_URL")
        key = key or os.environ.get("SUPABASE_KEY")

        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")

        self.client: Client = create_client(url, key)

    def insert_repos(self, repos: List[Dict], since_period: str = "daily") -> int:
        """Upsert owners, repos, and trending snapshots for one collection period."""
        if not repos:
            return 0

        today = date.today().isoformat()
        valid = [r for r in repos if "/" in r.get("repo_name", "")]

        try:
            # 1. Owners — insert new, leave existing untouched (analyze_repos enriches these)
            owner_rows = [{"owner_name": r["repo_name"].split("/")[0]} for r in valid]
            self.client.table("owners").upsert(
                owner_rows, on_conflict="owner_name", ignore_duplicates=True
            ).execute()

            # 2. Repos — upsert metadata; first_seen_date set by DB default on first insert
            repo_rows = [
                {
                    "repo_name": r["repo_name"],
                    "owner_name": r["repo_name"].split("/")[0],
                    "description": r.get("description"),
                    "language": r.get("language"),
                }
                for r in valid
            ]
            self.client.table("repos").upsert(
                repo_rows, on_conflict="repo_name"
            ).execute()

            # 3. Trending snapshots — the time-series core
            snapshot_rows = [
                {
                    "repo_name": r["repo_name"],
                    "collected_date": today,
                    "since_period": since_period,
                    "stars_in_period": r.get("stars_today"),
                    "total_stars": r.get("total_stars"),
                    "forks": r.get("forks"),
                    "rank": r.get("rank"),
                }
                for r in valid
            ]
            response = self.client.table("trending_snapshots").upsert(
                snapshot_rows, on_conflict="repo_name,collected_date,since_period"
            ).execute()

            count = len(response.data)
            print(f"Upserted {count} snapshots ({since_period})")
            return count

        except Exception as e:
            print(f"Insert failed ({since_period}): {e}")
            raise

    def get_last_collection(self) -> Dict | None:
        try:
            response = (
                self.client.table("trending_snapshots")
                .select("collected_at")
                .order("collected_at", desc=True)
                .limit(1)
                .execute()
            )
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error fetching last collection: {e}")
            return None
