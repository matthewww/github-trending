#!/usr/bin/env python3
"""Normalise repo_insight categories to the canonical taxonomy.

Two phases:
  1. Alias mapping (free, deterministic): case/spacing variants and known
     aliases are remapped to canonical categories. Idempotent safety net
     against LLM category drift.
  2. LLM re-triage (optional, --retake-other): repos sitting in 'Other' (or
     any category passed via --retake) are re-classified in batches using
     their purpose/description/themes. Requires GROQ_API_KEY.

Changed repos are re-embedded so the next cluster run reflects the new
categories (requires sentence-transformers, present in CI).
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from supabase_client import SupabaseClient

load_dotenv()

MODELS_ENDPOINT = "https://api.groq.com/openai/v1"
MODEL = os.environ.get("DIGEST_MODEL") or "openai/gpt-oss-120b"
REQUEST_DELAY = 5
RETAKE_BATCH_SIZE = 10

CANONICAL = [
    "AI/ML",
    "Developer Tools",
    "Security",
    "Infrastructure",
    "Education",
    "Web Framework",
    "Data Science",
    "Productivity",
    "Game/Creative",
    "Other",
]

# Deterministic alias -> canonical map (matched case/whitespace-insensitively)
ALIASES = {
    "ai": "AI/ML",
    "ai/ml": "AI/ML",
    "ai / ml": "AI/ML",
    "machine learning": "AI/ML",
    "ml": "AI/ML",
    "llm": "AI/ML",
    "generative ai": "AI/ML",
    "dev tools": "Developer Tools",
    "devtools": "Developer Tools",
    "developer tool": "Developer Tools",
    "developer-tools": "Developer Tools",
    "cli": "Developer Tools",
    "tooling": "Developer Tools",
    "web framework": "Web Framework",
    "web frameworks": "Web Framework",
    "web dev": "Web Framework",
    "web development": "Web Framework",
    "frontend": "Web Framework",
    "backend": "Web Framework",
    "data science": "Data Science",
    "data": "Data Science",
    "data engineering": "Data Science",
    "analytics": "Data Science",
    "databases": "Infrastructure",
    "database": "Infrastructure",
    "devops": "Infrastructure",
    "cloud": "Infrastructure",
    "networking": "Infrastructure",
    "infra": "Infrastructure",
    "security": "Security",
    "privacy": "Security",
    "cybersecurity": "Security",
    "education": "Education",
    "learning": "Education",
    "tutorial": "Education",
    "productivity": "Productivity",
    "notes": "Productivity",
    "games": "Game/Creative",
    "game": "Game/Creative",
    "gaming": "Game/Creative",
    "creative": "Game/Creative",
    "media": "Game/Creative",
    "art": "Game/Creative",
    "music": "Game/Creative",
    "other": "Other",
    "misc": "Other",
    "unknown": "Other",
}


def normalise_key(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def alias_map_category(raw: str) -> str | None:
    """Return the canonical category for raw, or None if it needs LLM triage."""
    if not raw:
        return None
    key = normalise_key(raw)
    if key in ALIASES:
        canonical = ALIASES[key]
        if canonical in CANONICAL:
            return canonical
    return None


def fetch_insights(db: SupabaseClient, categories: list[str] | None = None) -> list[dict]:
    query = db.client.table("repo_insights").select(
        "repo_name, category, purpose, key_themes"
    )
    if categories:
        query = query.in_("category", categories)
    # oldest analyses first so --limit re-triages the stalest entries
    return db.fetch_all(query.order("analyzed_at"))


def fetch_descriptions(db: SupabaseClient, names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    rows = db.fetch_all(
        db.client.table("repos").select("repo_name, description").in_("repo_name", names)
    )
    return {r["repo_name"]: (r.get("description") or "") for r in rows}


def retake_batch(llm_client: OpenAI, batch: list[dict], desc_map: dict[str, str]) -> dict[str, str]:
    """Ask the LLM to re-classify a batch of repos. Returns {repo_name: category}."""
    lines = []
    for r in batch:
        desc = desc_map.get(r["repo_name"], "")
        themes = ", ".join(r.get("key_themes") or [])
        lines.append(
            f"- {r['repo_name']}: purpose={r.get('purpose') or '(unknown)'}; "
            f"description={desc or '(none)'}; themes={themes or '(none)'}"
        )

    prompt = f"""Classify each repository below into exactly one of these categories:
{', '.join(CANONICAL)}

Rules:
- 'Other' is a last resort — use it only when nothing else fits
- Judge by what the repo DOES, not by its name alone
- AI/ML is for repos whose primary subject is AI/ML techniques, models, or AI-powered tools

Repositories:
{chr(10).join(lines)}

Return ONLY a JSON array: [{{"repo_name": "...", "category": "..."}}, ...]"""

    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a precise technical classifier. Always respond with valid JSON only, no markdown fences.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
        extra_body={"reasoning_effort": "low"},
    )
    raw = response.choices[0].message.content.strip()
    parsed = json.loads(raw)
    result = {}
    for item in parsed:
        name = item.get("repo_name")
        cat = item.get("category")
        if name and cat in CANONICAL:
            result[name] = cat
    return result


def reembed_changed(db: SupabaseClient, changed: dict[str, str], fresh: dict[str, dict]):
    """Re-embed repos whose category changed so clustering stays consistent."""
    try:
        from analyze_repos import build_embed_text, get_embedder
    except ImportError:
        print("  sentence-transformers unavailable — skipping re-embedding (clusters will refresh next weekly run)")
        return
    print(f"Re-embedding {len(changed)} changed repos...")
    for repo_name, new_cat in changed.items():
        insight = fresh.get(repo_name)
        if not insight:
            continue
        insight["category"] = new_cat
        try:
            text = build_embed_text(insight)
            if not text:
                continue
            vec = get_embedder().encode(text, normalize_embeddings=True).tolist()
            db.client.table("embeddings").upsert(
                {
                    "repo_name": repo_name,
                    "embedding": vec,
                    "source_text": text,
                    "model_used": "all-MiniLM-L6-v2",
                    "generated_at": datetime.utcnow().isoformat(),
                },
                on_conflict="repo_name",
            ).execute()
        except Exception as e:
            print(f"  re-embed failed for {repo_name}: {e}")


def apply_updates(db: SupabaseClient, updates: dict[str, str]) -> int:
    """Update categories grouped by target category. Returns rows written."""
    written = 0
    by_cat: dict[str, list[str]] = {}
    for name, cat in updates.items():
        by_cat.setdefault(cat, []).append(name)
    for cat, names in by_cat.items():
        for i in range(0, len(names), 100):
            chunk = names[i : i + 100]
            db.client.table("repo_insights").update({"category": cat}).in_(
                "repo_name", chunk
            ).execute()
            written += len(chunk)
    return written


def main():
    parser = argparse.ArgumentParser(description="Normalise repo categories to canonical taxonomy")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to Supabase (default: dry-run report only)")
    parser.add_argument("--retake-other", action="store_true",
                        help="LLM re-triage of repos currently in 'Other' (requires GROQ_API_KEY)")
    parser.add_argument("--retake", type=str, default=None,
                        help="Comma-separated list of categories to LLM re-triage (e.g. --retake 'Other,Productivity')")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of LLM re-triage repos processed")
    args = parser.parse_args()

    db = SupabaseClient()
    insights = fetch_insights(db)
    print(f"Loaded {len(insights)} insights")

    # Phase 1: deterministic alias mapping
    updates: dict[str, str] = {}
    for r in insights:
        current = r.get("category")
        canonical = alias_map_category(current)
        if canonical and canonical != current:
            updates[r["repo_name"]] = canonical

    print(f"\n--- Phase 1: alias mapping ---")
    if updates:
        for name, cat in sorted(updates.items()):
            current = next(r["category"] for r in insights if r["repo_name"] == name)
            print(f"  {name}: {current!r} -> {cat!r}")
    else:
        print("  All categories already canonical — nothing to remap")

    # Phase 2: LLM re-triage of weak buckets
    retake_cats = []
    if args.retake_other:
        retake_cats.append("Other")
    if args.retake:
        retake_cats.extend(c.strip() for c in args.retake.split(",") if c.strip())
    retake_cats = [c for c in dict.fromkeys(retake_cats) if c in CANONICAL]

    if retake_cats:
        groq_key = os.environ.get("GROQ_API_KEY")
        if not groq_key:
            print("\n--- Phase 2: LLM re-triage SKIPPED (GROQ_API_KEY not set) ---")
        else:
            pool = [r for r in insights if r.get("category") in retake_cats and r["repo_name"] not in updates]
            if args.limit:
                pool = pool[: args.limit]
            print(f"\n--- Phase 2: LLM re-triage of {len(pool)} repos in {retake_cats} ---")
            desc_map = fetch_descriptions(db, [r["repo_name"] for r in pool])
            llm_client = OpenAI(base_url=MODELS_ENDPOINT, api_key=groq_key)

            for i in range(0, len(pool), RETAKE_BATCH_SIZE):
                batch = pool[i : i + RETAKE_BATCH_SIZE]
                print(f"  batch {i // RETAKE_BATCH_SIZE + 1}/{(len(pool) + RETAKE_BATCH_SIZE - 1) // RETAKE_BATCH_SIZE} ({len(batch)} repos)")
                try:
                    result = retake_batch(llm_client, batch, desc_map)
                except Exception as e:
                    print(f"    batch failed: {e}")
                    continue
                for r in batch:
                    new_cat = result.get(r["repo_name"])
                    if new_cat and new_cat != r.get("category"):
                        updates[r["repo_name"]] = new_cat
                        print(f"    {r['repo_name']}: {r.get('category')} -> {new_cat}")
                    elif new_cat:
                        print(f"    {r['repo_name']}: stays {new_cat}")
                if i + RETAKE_BATCH_SIZE < len(pool):
                    time.sleep(REQUEST_DELAY)

    if not updates:
        print("\nNo category changes needed.")
        return 0

    print(f"\nTotal proposed changes: {len(updates)}")
    if not args.apply:
        print("Dry run — re-run with --apply to write changes.")
        return 0

    written = apply_updates(db, updates)
    print(f"Wrote {written} category updates")

    fresh = {r["repo_name"]: r for r in fetch_insights(db)}
    reembed_changed(db, updates, fresh)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
