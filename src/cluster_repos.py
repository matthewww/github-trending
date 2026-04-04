#!/usr/bin/env python3
"""Weekly clustering of repo embeddings via UMAP + HDBSCAN."""

import os
import sys
import json
import numpy as np
from datetime import date
from dotenv import load_dotenv
from openai import OpenAI
from supabase_client import SupabaseClient

load_dotenv()

MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o-mini"
MIN_CLUSTER_SIZE = 3
CENTROID_MATCH_THRESHOLD = 0.85  # cosine similarity to match prior-week cluster


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


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
    vecs = np.array([r["embedding"] for r in rows], dtype=np.float32)
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
            max_tokens=100,
        )
        data = json.loads(resp.choices[0].message.content.strip())
        return data.get("label", "Unnamed"), data.get("description", "")
    except Exception as e:
        print(f"  Cluster label failed: {e}")
        return "Unnamed Cluster", ""


def load_prior_clusters(db: SupabaseClient) -> list[dict]:
    """Most recent prior run's clusters with centroids."""
    resp = (
        db.client.table("clusters")
        .select("id, label, centroid, run_date")
        .order("run_date", desc=True)
        .limit(50)
        .execute()
    )
    rows = resp.data or []
    # Only from the single most recent run_date
    if not rows:
        return []
    latest_date = rows[0]["run_date"]
    return [r for r in rows if r["run_date"] == latest_date]


def match_prior_cluster(centroid: np.ndarray, prior_clusters: list[dict]) -> int | None:
    """Return prior cluster id if cosine similarity > threshold."""
    best_sim, best_id = 0.0, None
    for pc in prior_clusters:
        if pc["centroid"] is None:
            continue
        pc_vec = np.array(pc["centroid"], dtype=np.float32)
        sim = cosine_similarity(centroid, pc_vec)
        if sim > best_sim:
            best_sim, best_id = sim, pc["id"]
    if best_sim >= CENTROID_MATCH_THRESHOLD:
        return best_id
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

    llm_token = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    llm_client = OpenAI(base_url=MODELS_ENDPOINT, api_key=llm_token or "no-key")

    prior_clusters = load_prior_clusters(db)
    run_date = date.today().isoformat()

    # Build cluster → repo mapping
    cluster_repos: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if label >= 0:
            cluster_repos.setdefault(label, []).append(idx)

    # Write clusters and repo_cluster_map
    cluster_id_map: dict[int, int] = {}  # hdbscan label → db id

    for hdb_label in unique_clusters:
        idxs = cluster_repos[hdb_label]
        repo_names_in_cluster = [names[i] for i in idxs]

        # Centroid in original embedding space
        centroid = vecs[idxs].mean(axis=0)
        centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-10)

        print(f"  Cluster {hdb_label}: {len(idxs)} repos — labelling...")
        label_text, description = label_cluster(llm_client, repo_names_in_cluster, db)

        prev_id = match_prior_cluster(centroid_norm, prior_clusters)

        cluster_resp = (
            db.client.table("clusters")
            .insert({
                "run_date": run_date,
                "label": label_text,
                "description": description,
                "size": len(idxs),
                "centroid": centroid_norm.tolist(),
                "prev_cluster_id": prev_id,
            })
            .execute()
        )
        db_cluster_id = cluster_resp.data[0]["id"]
        cluster_id_map[hdb_label] = db_cluster_id
        print(f"    → '{label_text}' (id={db_cluster_id}, prev={prev_id})")

    # Write repo_cluster_map with UMAP 2D coords
    map_rows = []
    for idx, hdb_label in enumerate(labels):
        if hdb_label < 0:
            continue
        map_rows.append({
            "repo_name": names[idx],
            "cluster_id": cluster_id_map[hdb_label],
            "run_date": run_date,
            "umap_x": float(reduced_2[idx, 0]),
            "umap_y": float(reduced_2[idx, 1]),
        })

    if map_rows:
        # Delete old entries for today's run_date before inserting
        db.client.table("repo_cluster_map").delete().eq("run_date", run_date).execute()
        db.client.table("repo_cluster_map").insert(map_rows).execute()
        print(f"Wrote {len(map_rows)} repo→cluster mappings")

    print(f"\nClustering complete. {len(unique_clusters)} clusters written for {run_date}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
