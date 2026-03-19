#!/usr/bin/env python3
"""Main entry point for daily collection."""

import sys
from collect import fetch_trending
from supabase_client import SupabaseClient


def main():
    print("Starting GitHub trending collection...")

    try:
        repos = fetch_trending(since="daily")
        print(f"Fetched {len(repos)} trending repos")
    except Exception as e:
        print(f"Failed to fetch trending: {e}")
        return 1

    try:
        client = SupabaseClient()
        count = client.insert_repos(repos)
        print(f"Successfully stored {count} repos in Supabase")
        return 0
    except Exception as e:
        print(f"Failed to store in Supabase: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
