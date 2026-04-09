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


def fetch_longitudinal_context(db: SupabaseClient, week_start: date, weeks: int = 4) -> dict:
    """Fetch multi-week repo presence data for streak signals and per-week top-5 history.

    Returns:
      {
        "weekly_top5": [{"week": "YYYY-MM-DD", "repos": [{"repo_name", "max_stars_today", "purpose"}]}, ...],
        "streaks_this_week": ["repo_name", ...],   # 3+ days in trending this week
        "multi_week_runs": ["repo_name", ...],     # appeared in current + at least 1 prev week
        "drop_offs": ["repo_name", ...],           # appeared last week but NOT this week
      }
    """
    from collections import defaultdict
    start = week_start - timedelta(weeks=weeks - 1)
    end = week_start + timedelta(days=6)

    resp = (
        db.client.table("trending_snapshots")
        .select("repo_name, collected_date, stars_in_period")
        .eq("since_period", "daily")
        .gte("collected_date", start.isoformat())
        .lte("collected_date", end.isoformat())
        .execute()
    )
    rows = resp.data or []

    # Group by week_start → repo → list of (date, stars)
    week_repo_days: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        d = date.fromisoformat(r["collected_date"])
        w = (d - timedelta(days=d.weekday())).isoformat()
        week_repo_days[w][r["repo_name"]].append({
            "date": r["collected_date"],
            "stars": r.get("stars_in_period") or 0,
        })

    # Fetch purposes for enrichment
    all_names = list({r["repo_name"] for r in rows})
    purpose_map: dict[str, str] = {}
    if all_names:
        ins_resp = (
            db.client.table("repo_insights")
            .select("repo_name, purpose")
            .in_("repo_name", all_names)
            .execute()
        )
        purpose_map = {i["repo_name"]: i.get("purpose", "") for i in (ins_resp.data or [])}

    current_week_key = week_start.isoformat()
    prev_week_start = week_start - timedelta(weeks=1)
    prev_week_key = prev_week_start.isoformat()

    # Per-week top-5 by max daily stars (previous weeks only — current week shown in main context)
    weekly_top5 = []
    for w_key in sorted(week_repo_days.keys()):
        if w_key == current_week_key:
            continue
        week_repos = week_repo_days[w_key]
        ranked = sorted(
            [
                {"repo_name": rn, "max_stars_today": max(d["stars"] for d in days)}
                for rn, days in week_repos.items()
            ],
            key=lambda x: x["max_stars_today"],
            reverse=True,
        )[:5]
        for r in ranked:
            r["purpose"] = purpose_map.get(r["repo_name"], "")
        weekly_top5.append({"week": w_key, "repos": ranked})

    current_repos = week_repo_days.get(current_week_key, {})
    prev_repos = set(week_repo_days.get(prev_week_key, {}).keys())

    # Streaks: 3+ days in trending this week
    streaks_this_week = [
        rn for rn, days in current_repos.items() if len(days) >= 3
    ]

    # Multi-week runs: in current week AND at least one prior week
    prior_weeks = {k for k in week_repo_days if k != current_week_key}
    repos_in_any_prior = {rn for w in prior_weeks for rn in week_repo_days[w]}
    multi_week_runs = [rn for rn in current_repos if rn in repos_in_any_prior]

    # Drop-offs: in prev week but not this week
    drop_offs = [rn for rn in prev_repos if rn not in current_repos]

    return {
        "weekly_top5": weekly_top5,
        "streaks_this_week": streaks_this_week,
        "multi_week_runs": multi_week_runs,
        "drop_offs": drop_offs,
    }


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


def compute_data_quality(this_week: list[dict]) -> int:
    """Return % of repos this week that have LLM insights."""
    if not this_week:
        return 0
    analyzed = sum(1 for r in this_week if r.get("purpose"))
    return round(analyzed / len(this_week) * 100)


def build_context(
    week_start: date,
    week_end: date,
    this_week: list[dict],
    prev_week_names: set[str],
    category_history: list[dict],
    data_quality_pct: int = 100,
    longitudinal: dict | None = None,
) -> str:
    """Build a compact structured context string for the LLM prompt."""
    from collections import Counter, defaultdict
    lines = []

    lines.append(f"## Week of {week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')}")
    lines.append(f"Total unique repos trending: {len(this_week)}")
    lines.append(f"Repos with LLM analysis: {data_quality_pct}% (only analysed repos have purpose/category data)")
    lines.append("")

    # Top repos by star velocity (up to 10)
    top10 = this_week[:10]
    lines.append("## Top repos by daily stars (with days seen in trending this week)")
    for r in top10:
        purpose = f" — {r['purpose']}" if r.get("purpose") else " — (no analysis yet)"
        days = r.get("days_seen", 1)
        days_str = f", {days}d in trending" if days > 1 else ", 1d in trending"
        new_flag = " [NEW]" if r["repo_name"] not in prev_week_names else " [returning]"
        lines.append(
            f"- {r['repo_name']} ({r['language'] or '?'}, {r['max_stars_today']:,} stars/day"
            f"{days_str}{new_flag}): {r.get('category', 'Unknown')}{purpose}"
        )
    lines.append("")

    # Full repo list for the rest
    remaining = this_week[10:]
    if remaining:
        lines.append("## All other repos trending this week")
        for r in remaining:
            new_flag = " [NEW]" if r["repo_name"] not in prev_week_names else ""
            days = r.get("days_seen", 1)
            lines.append(
                f"- {r['repo_name']} ({r.get('category', 'Unknown')}, "
                f"{r['max_stars_today']:,} stars/day, {days}d{new_flag})"
            )
        lines.append("")

    # New vs returning summary
    new_count = sum(1 for r in this_week if r["repo_name"] not in prev_week_names)
    returning_count = len(this_week) - new_count
    lines.append(f"## New repos this week: {new_count} | Returning from last week: {returning_count}")
    lines.append("")

    # Category breakdown this week
    cat_counts = Counter(r.get("category", "Unknown") for r in this_week)
    lines.append("## Category breakdown this week")
    for cat, count in cat_counts.most_common():
        lines.append(f"- {cat}: {count}")
    lines.append("")

    # Category shift vs last week
    if len(category_history) >= 2:
        prev_hist = category_history[-2]["counts"]
        curr_hist = category_history[-1]["counts"]
        shifts = []
        all_cats = set(list(prev_hist.keys()) + list(curr_hist.keys()))
        for cat in sorted(all_cats):
            prev_n = prev_hist.get(cat, 0)
            curr_n = curr_hist.get(cat, 0)
            if prev_n != curr_n:
                arrow = "↑" if curr_n > prev_n else "↓"
                shifts.append(f"- {cat}: {curr_n} ({arrow} from {prev_n})")
        if shifts:
            lines.append("## Category shifts vs last week")
            lines.extend(shifts)
            lines.append("")

    # Creator connections — owners with multiple repos trending this week
    repos_by_owner: dict[str, list[str]] = defaultdict(list)
    for r in this_week:
        repos_by_owner[r["owner_name"]].append(r["repo_name"])

    multi_repo_owners = {o: repos for o, repos in repos_by_owner.items() if len(repos) > 1}
    if multi_repo_owners:
        lines.append("## Creators with multiple trending repos this week")
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
        lines.append("## Most common themes this week")
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

    # Longitudinal repo signals
    if longitudinal:
        weekly_top5 = longitudinal.get("weekly_top5", [])
        if weekly_top5:
            lines.append("## Top repos in previous weeks (for longitudinal comparison)")
            for week_entry in weekly_top5[-3:]:  # last 3 prior weeks
                w = week_entry["week"]
                repos_str = ", ".join(
                    f"{r['repo_name']} ({r['max_stars_today']:,}/day)"
                    + (f" — {r['purpose'][:60]}" if r.get("purpose") else "")
                    for r in week_entry["repos"]
                )
                lines.append(f"- {w}: {repos_str}")
            lines.append("")

        streaks = longitudinal.get("streaks_this_week", [])
        if streaks:
            lines.append(f"## Repos trending 3+ days this week (sustained): {', '.join(streaks)}")
            lines.append("")

        multi = longitudinal.get("multi_week_runs", [])
        if multi:
            lines.append(f"## Repos appearing in current + previous week(s): {', '.join(multi)}")
            lines.append("")

        drops = longitudinal.get("drop_offs", [])
        if drops:
            lines.append(f"## Repos that trended last week but disappeared this week: {', '.join(drops)}")
            lines.append("")

    return "\n".join(lines)


def generate_digest(llm_client: OpenAI, context: str, week_start: date) -> dict | None:
    prompt = f"""You are writing a weekly briefing on GitHub trending for a senior software developer who reads GitHub trending every day.

They can already see the category chart, the top repos by stars, and the languages. Do NOT describe those.
Your job: find what the data reveals that isn't immediately obvious from the charts.

STRICT RULES — violating any of these makes the digest worthless:
1. NEVER make generic statements like "AI tools are popular", "developer tools are surging", or anything that was true every week for the past year
2. NEVER say a category "dominated" or "led" this week — the reader can see the chart
3. EVERY claim must name at least one specific repository and give a concrete reason why it's notable
4. Find at least one thing that is SURPRISING or COUNTER-INTUITIVE in the data — if you find one, open with it
5. If multiple repos solve the same problem differently, say so explicitly: "repo-A, repo-B, and repo-C are all competing on X"
6. Explain WHY specific repos are likely trending right now — a new release, a viral moment, fills a gap vs alternatives, rides a specific event
7. Use "sustained presence" signals from the context: repos with 3+ days in trending or multi-week runs are stronger signals than one-day spikes
8. Use "drop-offs" from the context: if a repo trended last week but is gone this week, that's worth noting if it was significant
9. If your confidence is limited by data gaps (low analysis %), say what you CAN observe and flag uncertainty in confidence_notes

{context}

Return ONLY valid JSON with these exact fields:
{{
  "headline": "One specific sentence naming a repo, an owner, or a concrete pattern — NOT a generic trend statement",
  "digest": "350-450 word prose in 3-4 paragraphs separated by \\n\\n. Each paragraph must contain at least one named repo with a specific reason for its prominence. No paragraph may consist only of category-level observations.",
  "top_categories": ["ordered list of top 4 categories this week by repo count"],
  "emerging_themes": ["3-5 themes that are specifically concentrated or newly appearing this week — name the repos that exemplify each"],
  "confidence_notes": "One sentence: what limited your analysis this week (low coverage, many repos without insights, etc.), or 'Good data coverage' if the analysis %, star data, and purposes are solid"
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
            max_tokens=1100,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}\nRaw: {raw[:200]}")
        return None
    except Exception as e:
        print(f"LLM call failed: {e}")
        return None


def upsert_digest(
    db: SupabaseClient,
    week_start: date,
    week_end: date,
    result: dict,
    data_quality_pct: int,
    confidence_label: str,
):
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
        "data_quality_pct": data_quality_pct,
        "confidence_label": confidence_label,
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

    data_quality_pct = compute_data_quality(this_week)
    print(f"  Data quality: {data_quality_pct}% of repos have LLM insights")

    if data_quality_pct == 0:
        print("0% of repos have insights — nothing to analyse, skipping digest generation")
        return 0

    confidence_label = "high" if data_quality_pct >= 80 else ("medium" if data_quality_pct >= 50 else "low")
    print(f"  Confidence label: {confidence_label}")

    prev_week_names = fetch_prev_week_repos(db, week_start)
    category_history = fetch_category_history(db, week_start)
    longitudinal = fetch_longitudinal_context(db, week_start)
    print(f"  Streaks (3+ days): {len(longitudinal['streaks_this_week'])} repos")
    print(f"  Multi-week runs: {len(longitudinal['multi_week_runs'])} repos")
    print(f"  Drop-offs from last week: {len(longitudinal['drop_offs'])} repos")

    context = build_context(week_start, week_end, this_week, prev_week_names, category_history, data_quality_pct, longitudinal)

    sys.stdout.buffer.write(f"\n--- Context ({len(context)} chars) ---\n{context}\n---\n".encode('utf-8', 'replace'))
    sys.stdout.buffer.flush()

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

    upsert_digest(db, week_start, week_end, result, data_quality_pct, confidence_label)
    print(f"\n✓ Digest saved for week of {week_start}")
    print(f"\nHeadline: {result.get('headline')}")
    print(f"Confidence notes: {result.get('confidence_notes', '')}")
    print(f"\n{result.get('digest', '')[:300]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
