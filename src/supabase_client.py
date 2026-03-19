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

    def insert_repos(self, repos: List[Dict]) -> int:
        if not repos:
            return 0

        try:
            today = date.today().isoformat()
            for repo in repos:
                repo["collected_date"] = today

            response = (
                self.client.table("repositories")
                .upsert(repos, on_conflict="repo_name,collected_date")
                .execute()
            )
            print(f"Upserted {len(response.data)} repos")
            return len(response.data)
        except Exception as e:
            print(f"Insert failed: {e}")
            raise

    def get_last_collection(self) -> Dict or None:
        try:
            response = (
                self.client.table("repositories")
                .select("collected_at")
                .order("collected_at", desc=True)
                .limit(1)
                .execute()
            )
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error fetching last collection: {e}")
            return None
