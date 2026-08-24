#!/usr/bin/env python3
"""Weekly clustering of repo embeddings via UMAP + HDBSCAN."""

import os
import sys
import json
import numpy as np
from datetime import date, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from supabase_client import SupabaseClient

load_dotenv()

MODELS_ENDPOINT = "https://api.groq.com/openai/v1"
MODEL = "openai/gpt-oss-120b"
MIN_CLUSTER_SIZE = 3
JACCARD_MATCH_THRESHOLD = 0.4  # membership overlap to inherit a stable cluster key
JACCARD_MIN_FALLBACK = 0.2     # below this, never inherit regardless of centroid
CENTROID_MATCH_THRESHOLD = 0.85  # cosine similarity fallback for drifted clusters
RETIRE_AFTER_DAYS = 21  # registry rows unseen this long are marked retired


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def slugify(label: str, taken: set) -> str:
    base = "".join(c if c.isalnum() else "-" for c in label.lower())
    base = "-".join(p for p in base.split("-") if p)[:48] or "cluster"
    key, n = base, 2
    while key in taken:
        key = f"{base}-{n}"
        n += 1
    return key


def load_embeddings(db: SupabaseClient) -> tuple[list[str], np.ndarray]:
    """Return (repo_names, embedding_matrix)."""
    resp = (
        db.client.table("embeddings")
        .select("repo_name, embedding")
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return [], np.array([])

    names = [r["repo_name"] for r in rows]
    raw = [r["embedding"] for r in rows]
    # Supabase returns pgvector as a string like "[0.1,0.2,...]"
    parsed = [
        json.loads(e) if isinstance(e, str) else e
        for e in raw
    ]
    vecs = np.array(parsed, dtype=np.float32)
    return names, vecs


def run_umap(vecs: np.ndarray, n_components: int, metric: str = "cosine") -> np.ndarray:
    import umap
    reducer = umap.UMAP(
        n_components=n_components,
        metric=metric,
        min_dist=0.0,
        random_state=42,
        verbose=False,
    )
    return reducer.fit_transform(vecs)


def run_hdbscan(reduced: np.ndarray) -> np.ndarray:
    import hdbscan
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    return clusterer.fit_predict(reduced)


def label_cluster(client: OpenAI, repo_names: list[str], db: SupabaseClient) -> tuple[str, str]:
    """Ask LLM for a cluster label + 1-sentence description from top repo purposes."""
    insights_resp = (
        db.client.table("repo_insights")
        .select("repo_name, purpose, category")
        .in_("repo_name", repo_names[:10])
        .execute()
    )
    insights = insights_resp.data or []
    if not insights:
        return "Unnamed Cluster", ""

    summaries = "\n".join(
        f"- {i['repo_name']}: {i.get('purpose','')}" for i in insights
    )
    prompt = (
        f"These GitHub repositories are in the same semantic cluster:\n{summaries}\n\n"
        "Return ONLY a JSON object with:\n"
        '{"label": "2-4 word cluster name", "description": "one sentence describing the cluster theme"}'
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical analyst. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=512,
            extra_body={"reasoning_effort": "low"},
        )
        data = json.loads(resp.choices[0].message.content.strip())
        return data.get("label", "Unnamed"), data.get("description", "")
    except Exception as e:
        print(f"  Cluster label failed: {e}")
        return "Unnamed Cluster", ""


def load_prior_identity(db: SupabaseClient) -> dict:
    """Most recent prior run's clusters with stable keys, labels and member sets."""
    latest = (
        db.client.table("clusters")
        .select("run_date")
        .not_.is_("cluster_key", "null")
        .order("run_date", desc=True)
        .limit(1)
        .execute()
    )
    rows = latest.data or []
    if not rows:
        return {"run_date": None, "clusters": [], "members": {}, "repo_state": {}}
    prior_date = rows[0]["run_date"]

    clusters_resp = (
        db.client.table("clusters")
        .select("id, cluster_key, label, description, centroid")
        .eq("run_date", prior_date)
        .execute()
    )
    clusters = clusters_resp.data or []

    map_resp = (
        db.client.table("repo_cluster_map")
        .select("repo_name, cluster_id, stable_cluster_key, candidate_cluster_key")
        .eq("run_date", prior_date)
        .execute()
    )
    map_rows = map_resp.data or []

    members: dict[int, set] = {}
    repo_state: dict[str, dict] = {}
    for row in map_rows:
        members.setdefault(row["cluster_id"], set()).add(row["repo_name"])
        repo_state[row["repo_name"]] = {
            "stable": row.get("stable_cluster_key"),
            "candidate": row.get("candidate_cluster_key"),
        }

    return {"run_date": prior_date, "clusters": clusters, "members": members, "repo_state": repo_state}


def load_registry(db: SupabaseClient) -> dict[str, dict]:
    resp = db.client.table("cluster_registry").select("*").execute()
    return {row["cluster_key"]: row for row in (resp.data or [])}


def match_prior_cluster(
    members: set, centroid: np.ndarray, prior: dict, used_keys: set
) -> dict | None:
    """Inherit a stable cluster key by membership overlap, centroid as fallback."""
    best_j, best = 0.0, None
    for pc in prior["clusters"]:
        if pc["cluster_key"] in used_keys:
            continue
        jac = jaccard(members, prior["members"].get(pc["id"], set()))
        if jac > best_j:
            best_j, best = jac, pc
    if best is not None and best_j >= JACCARD_MATCH_THRESHOLD:
        return best

    # Fallback for drifted clusters: modest overlap + high centroid similarity.
    if best is not None and best_j >= JACCARD_MIN_FALLBACK and best["centroid"] is not None:
        raw = best["centroid"]
        pc_vec = np.array(json.loads(raw) if isinstance(raw, str) else raw, dtype=np.float32)
        if cosine_similarity(centroid, pc_vec) >= CENTROID_MATCH_THRESHOLD:
            return best
    return None


def main():
    db = SupabaseClient()

    print("Loading embeddings...")
    names, vecs = load_embeddings(db)
    if len(names) < MIN_CLUSTER_SIZE * 2:
        print(f"Not enough embeddings to cluster ({len(names)} repos). Need at least {MIN_CLUSTER_SIZE * 2}.")
        return 0

    print(f"  {len(names)} repos loaded")

    # UMAP: 384-dim → 15-dim for clustering
    print("Running UMAP (384→15)...")
    reduced_15 = run_umap(vecs, n_components=15)

    # UMAP: 384-dim → 2-dim for dashboard scatter
    print("Running UMAP (384→2) for scatter plot...")
    reduced_2 = run_umap(vecs, n_components=2)

    # HDBSCAN on 15-dim
    print("Running HDBSCAN...")
    labels = run_hdbscan(reduced_15)

    cluster_ids = [l for l in labels if l >= 0]
    noise_count = sum(1 for l in labels if l < 0)
    unique_clusters = sorted(set(cluster_ids))
    print(f"  Found {len(unique_clusters)} clusters, {noise_count} noise points")

    if not unique_clusters:
        print("No clusters found. Try collecting more data.")
        return 0

    llm_client = OpenAI(base_url=MODELS_ENDPOINT, api_key=os.environ.get("GROQ_API_KEY") or "no-key")

    prior = load_prior_identity(db)
    registry = load_registry(db)
    run_date = date.today().isoformat()
    taken_slugs = set(registry.keys())

    # Remove any existing clusters for today to avoid duplicates on re-run
    existing = db.client.table("clusters").select("id").eq("run_date", run_date).execute()
    existing_ids = [r["id"] for r in (existing.data or [])]
    if existing_ids:
        db.client.table("repo_cluster_map").delete().in_("cluster_id", existing_ids).execute()
        db.client.table("clusters").delete().eq("run_date", run_date).execute()
        db.client.table("cluster_weeks").delete().eq("week", run_date).execute()
        print(f"  Cleared {len(existing_ids)} existing clusters for {run_date}")

    # Build cluster → repo mapping
    cluster_repos: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if label >= 0:
            cluster_repos.setdefault(label, []).append(idx)

    new_registry_rows: list[dict] = []
    registry_updates: dict[str, dict] = {}
    used_keys: set[str] = set()
    cluster_week_rows: list[dict] = []
    cluster_id_map: dict[int, int] = {}  # hdbscan label → db id
    repo_cluster_keys: dict[str, str] = {}  # repo_name → stable key this run

    for hdb_label in unique_clusters:
        idxs = cluster_repos[hdb_label]
        repo_names_in_cluster = [names[i] for i in idxs]
        member_set = set(repo_names_in_cluster)

        # Centroid in original embedding space
        centroid = vecs[idxs].mean(axis=0)
        centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-10)

        match = match_prior_cluster(member_set, centroid_norm, prior, used_keys)
        if match:
            cluster_key = match["cluster_key"]
            used_keys.add(cluster_key)
            label_text = match["label"] or "Unnamed Cluster"
            description = match.get("description") or ""
            reg = registry.get(cluster_key)
            if reg:
                registry_updates[cluster_key] = {
                    "last_seen": run_date,
                    "weeks_seen": (reg.get("weeks_seen") or 1) + 1,
                }
            print(f"  Cluster {hdb_label}: {len(idxs)} repos — inherited '{cluster_key}' ('{label_text}')")
        else:
            label_text, description = label_cluster(llm_client, repo_names_in_cluster, db)
            cluster_key = slugify(label_text, taken_slugs)
            taken_slugs.add(cluster_key)
            new_registry_rows.append({
                "cluster_key": cluster_key,
                "label": label_text,
                "description": description,
                "first_seen": run_date,
                "last_seen": run_date,
                "weeks_seen": 1,
                "status": "active",
            })
            print(f"  Cluster {hdb_label}: {len(idxs)} repos — new cluster '{cluster_key}' ('{label_text}')")

        for name in repo_names_in_cluster:
            repo_cluster_keys[name] = cluster_key

        cluster_week_rows.append({"cluster_key": cluster_key, "week": run_date, "size": len(idxs)})

        cluster_resp = (
            db.client.table("clusters")
            .insert({
                "run_date": run_date,
                "cluster_key": cluster_key,
                "label": label_text,
                "description": description,
                "size": len(idxs),
                "centroid": centroid_norm.tolist(),
            })
            .execute()
        )
        db_cluster_id = cluster_resp.data[0]["id"]
        cluster_id_map[hdb_label] = db_cluster_id

    # Registry maintenance: insert newborns, refresh survivors, retire stale ones
    if new_registry_rows:
        db.client.table("cluster_registry").insert(new_registry_rows).execute()
    for key, upd in registry_updates.items():
        db.client.table("cluster_registry").update(upd).eq("cluster_key", key).execute()
    retire_cutoff = (date.today() - timedelta(days=RETIRE_AFTER_DAYS)).isoformat()
    for key, reg in registry.items():
        if key in used_keys or reg.get("status") != "active":
            continue
        if (reg.get("last_seen") or "") <= retire_cutoff:
            db.client.table("cluster_registry").update({"status": "retired"}).eq("cluster_key", key).execute()
            print(f"  Retired cluster '{key}' (last seen {reg.get('last_seen')})")

    if cluster_week_rows:
        db.client.table("cluster_weeks").insert(cluster_week_rows).execute()

    # Write repo_cluster_map with UMAP 2D coords + stable-key migration state
    map_rows = []
    prior_repo_state = prior.get("repo_state", {})
    for idx, hdb_label in enumerate(labels):
        if hdb_label < 0:
            continue
        repo_name = names[idx]
        new_key = repo_cluster_keys[repo_name]
        state = prior_repo_state.get(repo_name) or {}
        stable, candidate = state.get("stable"), state.get("candidate")
        if not stable or stable == new_key:
            new_stable, new_candidate = new_key, None
        elif candidate == new_key:
            new_stable, new_candidate = new_key, None  # confirmed after 2 runs
        else:
            new_stable, new_candidate = stable, new_key  # pending migration
        map_rows.append({
            "repo_name": repo_name,
            "cluster_id": cluster_id_map[hdb_label],
            "run_date": run_date,
            "umap_x": float(reduced_2[idx, 0]),
            "umap_y": float(reduced_2[idx, 1]),
            "stable_cluster_key": new_stable,
            "candidate_cluster_key": new_candidate,
        })

    if map_rows:
        # Delete old entries for today's run_date before inserting
        db.client.table("repo_cluster_map").delete().eq("run_date", run_date).execute()
        db.client.table("repo_cluster_map").insert(map_rows).execute()
        migrated = sum(1 for r in map_rows if r["candidate_cluster_key"] is None and r["stable_cluster_key"])
        print(f"Wrote {len(map_rows)} repo→cluster mappings ({migrated} with settled stable keys)")

    matched = len(used_keys)
    print(f"\nClustering complete: {len(unique_clusters)} clusters ({matched} inherited, "
          f"{len(unique_clusters) - matched} new) for {run_date}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
