#!/usr/bin/env python3
"""Main entry point for daily collection."""

import sys
from collect import fetch_trending
from supabase_client import SupabaseClient

PERIODS = ["daily", "weekly", "monthly"]


def main():
    print("Starting GitHub trending collection...")

    try:
        client = SupabaseClient()
    except Exception as e:
        print(f"Failed to initialise Supabase client: {e}")
        return 1

    total = 0
    failed = []

    for period in PERIODS:
        try:
            repos = fetch_trending(since=period)
            print(f"Fetched {len(repos)} trending repos ({period})")
            count = client.insert_repos(repos, since_period=period)
            total += count
        except Exception as e:
            print(f"Failed for period '{period}': {e}")
            failed.append(period)

    print(f"\nDone. {total} snapshots stored across {len(PERIODS) - len(failed)} period(s).")

    if failed:
        print(f"Failed periods: {', '.join(failed)}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
