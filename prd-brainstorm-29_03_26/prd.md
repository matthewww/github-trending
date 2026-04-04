# Product Requirements Document (PRD)

## GitHub Trend Intelligence Platform

---

## 1. Overview

This product aims to transform raw GitHub repository activity into a **dynamic map of emerging ideas, technologies, and developer behavior**.

Rather than focusing on individual repositories or static categories, the system will identify and track **evolving clusters of innovation over time**, enabling users to:

* Understand **what developers are building**
* Detect **emerging trends early**
* Identify **high-potential opportunity spaces**
* Observe how **communities shift and evolve**

This is especially relevant in the context of AI, where code generation has dramatically increased output volume, making **signal extraction more difficult and more valuable**.

---

## 2. Problem Statement

### Core Problem

GitHub activity is:

* High volume
* Noisy (especially due to AI-generated code)
* Poorly structured for trend analysis

Traditional approaches (e.g., stars, tags, or categories like “AI”) are insufficient because:

* They are **too coarse**
* They become **outdated quickly**
* They fail to capture **emerging or hybrid concepts**

### Key Challenge

> How do we identify meaningful trends without imposing rigid, outdated categorisation?

---

## 3. Goals & Objectives

### Primary Goal

Build a system that can:

> **Continuously map and track the evolution of software ideas on GitHub**

### Secondary Goals

* Detect **early-stage trends before mainstream adoption**
* Differentiate **hype vs sustained growth**
* Identify **high-density vs emerging opportunity spaces**
* Enable **interactive exploration of the GitHub ecosystem**

---

## 4. Non-Goals

* Building a GitHub client or repository browser
* Manual taxonomy or rigid categorisation systems
* Perfect semantic understanding (focus is directional insight, not precision)

---

## 5. Key Concepts

### 5.1 Unit of Analysis

Not:

* Individual repositories

But:

* **Clusters of related ideas**

---

### 5.2 Core Insight Model

The system is based on three layers:

1. **Raw Activity**

   * Repositories, commits, stars, contributors

2. **Semantic Understanding**

   * Embeddings of repo content
   * LLM-generated tags

3. **Emergent Structure**

   * Clusters of related repos
   * Evolution of those clusters over time

---

## 6. Functional Requirements

### 6.1 Data Ingestion

**Sources:**

* GitHub Trending (daily, weekly, monthly)
* GitHub API (repository metadata)

**Captured Data:**

* Repo name, description
* Stars, forks, watchers
* Contributors
* Commits
* Topics/tags
* README content

---

### 6.2 Data Enrichment

For each repository:

#### a) Embeddings

* Generate vector embeddings from:

  * README
  * Description
  * Tags

#### b) LLM Tagging

* Generate 3–5 semantic tags per repo
* Tags should reflect:

  * Purpose
  * Domain
  * Approach (e.g., “AI coding agent”, “local-first database”)

---

### 6.3 Storage (Supabase)

**Current schema (post-redesign, April 2026):**

#### `owners`
- `owner_name` (PK) — GitHub username/org
- `owner_type` — `individual` | `company` | `academic` | `unknown`
- `description` — LLM-generated owner summary

#### `repos`
- `repo_name` (PK) — `owner/name`
- `description`, `language`, `topics` (array), `readme_content` (text)
- `owner_name` (FK → owners)
- `total_stars`, `forks`
- `first_seen_date`

#### `trending_snapshots`
- `repo_name`, `collected_date`, `since_period` (daily/weekly/monthly) — composite PK
- `stars_in_period`, `total_stars`, `forks`, `rank`

#### `repo_insights`
- `repo_name` (PK, FK → repos)
- `purpose`, `category`, `key_themes` (array), `target_audience`

#### `weekly_digest`
- `week_start` (PK), `week_end`
- `headline`, `digest` (prose), `top_categories`, `top_repos`, `emerging_themes`

#### `embeddings`
- `repo_name` (PK, FK → repos)
- `embedding` — `vector(1536)` (pgvector, matches `text-embedding-3-small`)
- `embedded_at`, `model_used`

#### `clusters`
- `cluster_id` (PK)
- `label` — LLM-generated human-readable name
- `centroid` — `vector(1536)`
- `run_date`, `repo_count`, `description`

#### `repo_cluster_map`
- `repo_name`, `run_date` — composite PK
- `cluster_id` (FK → clusters)
- `distance_to_centroid`

---

### 6.4 Clustering

* Use unsupervised clustering (e.g., HDBSCAN)
* Run periodically (e.g., daily or weekly)
* Assign repositories to clusters

---

### 6.5 Trend Detection

For each cluster:

Track:

* Repo count over time
* Star velocity
* Contributor growth
* Tag frequency changes

---

### 6.6 Metrics

#### Growth Metrics

* Stars/day
* Contributors/week

#### Engagement Metrics

* Commits per contributor
* Issues/activity

#### Structural Metrics

* Cluster density
* Cluster growth rate

#### Novelty Metric

* Distance from existing clusters (embedding space)

---

## 7. Visualisation Requirements

### 7.1 Cluster Map (Core View)

* 2D projection (UMAP/t-SNE)
* Each point = repository
* Grouped into visible clusters

**Enhancements:**

* Color by cluster
* Size by activity (stars, contributors)

---

### 7.2 Cluster-Level View

Each cluster displays:

* Label (LLM-generated)
* Growth over time
* Top repositories
* Dominant tags

---

### 7.3 Trend Visualisations

#### a) Bubble Chart

* X: Time
* Y: Growth rate
* Size: Engagement
* Color: Cluster

#### b) Time Series

* Cluster growth curves
* Tag frequency trends

#### c) Animated Evolution (future)

* Cluster formation and splitting over time

---

## 8. Categorisation Strategy

### Key Principle

> Avoid fixed categories. Use **emergent structure**.

---

### Approach

#### Step 1: Embeddings

* Represent semantic meaning of repos

#### Step 2: Clustering

* Identify natural groupings

#### Step 3: LLM Labeling

* Assign human-readable labels to clusters

#### Step 4: Tag Graph

* Track relationships between tags over time

---

### Outcome

Categories become:

* Dynamic
* Contextual
* Evolvable

---

## 9. System Architecture

### Pipeline

1. **Ingestion**
2. **Enrichment (Embeddings + Tags)**
3. **Storage (Supabase)**
4. **Clustering Job**
5. **Analytics Layer**
6. **Visualisation Layer**

---

### Suggested Stack

* **Backend:** Python (data pipeline)
* **Database:** Supabase (Postgres + pgvector, `eu-west-1`)
* **Embeddings:** OpenAI `text-embedding-3-small` (1536-dim, ~$0.02/1M tokens)
  - New secret required: `OPENAI_API_KEY`
  - GitHub Models API does not support embedding models (chat-only)
  - Embedding source: concatenation of `description + topics + purpose + key_themes`
  - Batch via `embed_repos.py` — run weekly after `analyze_repos.py`
* **Clustering:** HDBSCAN (`hdbscan` Python package) + UMAP for 2D projection
  - Frequency: **weekly** (Sundays, after analysis job) — daily is too noisy to observe evolution
  - Minimum cluster size: 3 repos; discard clusters with `Unknown` label only
  - Script: `cluster_repos.py` — reads `embeddings`, writes `clusters` + `repo_cluster_map`
* **Frontend:**
  - Current: Static SPA on GitHub Pages (vanilla JS, Chart.js, reads `snapshot.json`)
  - Phase 3: Add cluster map tab — UMAP coords pre-computed and embedded in `snapshot.json`
  - Phase 4: Consider React + D3 if interactivity demands exceed static SPA

---

## 10. Phased Implementation Plan

### Phase 1 – Foundation ✅ Complete

* ✅ Daily/weekly/monthly trending scraper (`collect.py`, `main.py`)
* ✅ Supabase storage with owners + repos + trending_snapshots schema
* ✅ LLM enrichment: purpose, category, key_themes per repo (`analyze_repos.py`)
* ✅ Weekly prose digest generation (`generate_digest.py`)
* ✅ Static dashboard on GitHub Pages — digest hero, period tabs, category trend chart, language comparison, owner spotlight, date archive (`dashboard/index.html`, `export_data.py`)

---

### Phase 2 – Semantic Layer

**Goal:** Give every repo a vector position so we can find similarity and clusters.

**New secret needed:** `OPENAI_API_KEY`

**New pip deps:** `openai`, `hdbscan`, `umap-learn`, `scikit-learn`

#### Step 1 — `src/embed_repos.py`
- Query `repos LEFT JOIN embeddings` where `embedded_at IS NULL`
- For each repo, concatenate: `f"{description}. Topics: {topics}. Purpose: {purpose}. Themes: {key_themes}"`
- Call `openai.embeddings.create(model="text-embedding-3-small", input=text)`
- Upsert into `embeddings(repo_name, embedding, embedded_at, model_used)`
- Batch 100 repos per run; sleep 0.5s between calls

#### Step 2 — `src/cluster_repos.py`
- Load all rows from `embeddings` as numpy array
- Run `hdbscan.HDBSCAN(min_cluster_size=3).fit(vectors)`
- For each cluster: compute centroid, call LLM to generate a label from the top-5 repo descriptions
- Write to `clusters(cluster_id, label, centroid, run_date, repo_count, description)`
- Write to `repo_cluster_map(repo_name, run_date, cluster_id, distance_to_centroid)`

#### Step 3 — Add to `collect-daily.yml` (weekly step, Sundays)
```yaml
embed:
  needs: analyze
  if: github.event_name == 'schedule' && ...  # only on Sundays
  run: python src/embed_repos.py && python src/cluster_repos.py
```

#### Step 4 — Cluster stability strategy
- Each weekly run produces a new `run_date` partition in `repo_cluster_map`
- Match new clusters to prior-week clusters by centroid cosine similarity (>0.85 = same cluster)
- Store `prev_cluster_id` on `clusters` for continuity tracking
- Clusters with no match = newly emerged; clusters with no repos this week = dissolved

---

### Phase 3 – Trend Intelligence

* Track cluster growth (repo count, star velocity) over `run_date` partitions
* Add novelty score: distance of new repo's embedding from its nearest existing cluster centroid
  - Threshold: >0.4 cosine distance = "novel" (tune empirically)
* Add UMAP 2D coordinates to `snapshot.json` for cluster map view in dashboard
* Dashboard: cluster bubble chart (x=time, y=growth, size=engagement, color=cluster)

---

### Phase 4 – Advanced Insights

* Cluster evolution: detect splits (one cluster → two) and merges using centroid trajectory
* Tag graph: track co-occurrence of `key_themes` across repos over time
* Predictive signals: flag clusters with accelerating star velocity as "breakout"
* Alerting: GitHub issue or email digest when a new cluster passes the novelty + growth threshold

---

## 11. Success Metrics

### Product Success

* Ability to identify trends before mainstream awareness
* Clear differentiation between hype and sustained growth
* Discovery of “emerging clusters” with high growth

---

### Technical Success

* Stable clustering over time
* Meaningful, interpretable cluster labels
* Scalable ingestion + processing pipeline

---

## 12. Risks & Mitigations

### Risk: Noise from AI-generated repos

**Mitigation:**

* Focus on sustained growth
* Use contributor diversity as signal

---

### Risk: Poor clustering quality

**Mitigation:**

* Tune embeddings
* Experiment with clustering algorithms

---

### Risk: Overfitting categories

**Mitigation:**

* Avoid predefined taxonomy
* Use post-hoc labeling

---

### Risk: Data sparsity for new repos

**Mitigation:**

* Use embeddings + early velocity signals

---

## 13. Key Insight (Guiding Principle)

> The goal is not to classify GitHub.
>
> The goal is to **map it as a living system and observe how it evolves over time.**

---

## 14. Future Opportunities

* Integration with Hacker News / Reddit for cross-signal validation
* Investment / startup signal detection
* Developer tooling recommendations
* Personalised trend feeds

---

## 15. Open Questions

* How frequently should clustering run?
* What is the optimal embedding source?
* How to detect and label cluster splits/merges?
* What defines a “meaningful” trend threshold?

---

## 16. Current Environment (Existing Project)

> Context: A prior project (`matthewww/github-trending`) has been running in production. This section captures the tooling, credentials, and dataset available to carry forward into the new repo.

### Infrastructure

| Item | Detail |
|------|--------|
| **Supabase project** | `gh-trends` — `opnvgqhnqltlooshzrfj.supabase.co`, region `eu-west-1`, Postgres 17 |
| **GitHub repo** | `matthewww/github-trending` |
| **GitHub Actions** | Daily collect (10:00 UTC), Weekly analyze+digest (Sun 11:00 UTC), GitHub Pages deploy |
| **Python** | 3.11 |

### Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `SUPABASE_URL` | `https://opnvgqhnqltlooshzrfj.supabase.co` |
| `SUPABASE_KEY` | Supabase anon key |
| `GH_MODELS_TOKEN` | PAT with `models:read` scope — used to call GitHub Models API |
| `GITHUB_TOKEN` | Built-in Actions token — used for GitHub REST API (README fetch, repo metadata) |

### LLM

- **Provider:** GitHub Models API (`https://models.inference.ai.azure.com`)
- **Model:** `gpt-4o-mini` (OpenAI-compatible endpoint)
- **Auth:** Bearer token via `GH_MODELS_TOKEN`
- **Note:** Free tier — requires throttling (~5s delay between calls)

### GitHub Endpoints

#### Trending Scrape (HTML, no auth required)

```
https://github.com/trending?since=daily     # Top 25, stars gained today
https://github.com/trending?since=weekly    # Top 25, stars gained this week
https://github.com/trending?since=monthly   # Top 25, stars gained this month
https://github.com/trending/{language}?since=...  # Filter by language
```

Scraped via BeautifulSoup. Returns: repo name, description, language, stars in period, total stars, forks, rank (1–25).

> ✅ Now collecting all three periods per run (`daily`, `weekly`, `monthly`) — tripled signal density.

#### GitHub REST API (auth: `GITHUB_TOKEN`, 5,000 req/hr authenticated)

```
GET https://api.github.com/repos/{owner}/{repo}         # metadata: description, topics, owner type
GET https://api.github.com/repos/{owner}/{repo}/readme  # README content (base64-encoded)
```

#### GitHub Models API (auth: `GH_MODELS_TOKEN`)

```
POST https://models.inference.ai.azure.com/chat/completions
```

> Note: GitHub Models supports **chat only** — no embedding models. Embeddings require a separate `OPENAI_API_KEY`.

### Current Dataset (April 2026, post-schema redesign)

| Table | Rows | Content |
|-------|------|---------|
| `owners` | ~180 | GitHub usernames/orgs with `owner_type` and LLM description |
| `repos` | ~192 | Unique repos with description, language, topics, first\_seen\_date |
| `trending_snapshots` | ~1,400+ | Daily/weekly/monthly snapshots since Feb 17, 2026 |
| `repo_insights` | ~120 | LLM-generated: purpose, category, key\_themes, target\_audience |
| `weekly_digest` | 2 | Prose digests with headline, emerging\_themes, top\_categories |
| `embeddings` | 0 | Phase 2 — not yet populated |
| `clusters` | 0 | Phase 2 — not yet populated |
| `repo_cluster_map` | 0 | Phase 2 — not yet populated |

### What's Built (Current State)

| Component | Status |
|-----------|--------|
| Daily/weekly/monthly trending scraper | ✅ Production |
| Supabase storage — owners, repos, trending\_snapshots | ✅ Production |
| LLM enrichment — purpose, category, key\_themes | ✅ Production |
| Owner type + description enrichment | ✅ Production |
| Weekly prose digest generation | ✅ Production |
| Static dashboard (GitHub Pages) — digest, period tabs, charts, archive | ✅ Production |
| Daily JSON snapshot export (`export_data.py`) | ✅ Production |
| Date archive with dropdown | ✅ Production |
| Vector embeddings (`embed_repos.py`) | ❌ Phase 2 |
| Clustering — HDBSCAN + UMAP (`cluster_repos.py`) | ❌ Phase 2 |
| Cluster stability tracking | ❌ Phase 2 |
| Novelty detection | ❌ Phase 3 |
| Cluster map visualisation | ❌ Phase 3 |
| Cluster evolution (split/merge) | ❌ Phase 4 |

---

## 17. Summary

This system shifts from:

* Static categorisation → Dynamic mapping
* Repo-level metrics → Idea-level trends
* Snapshot views → Evolution over time

If executed well, it becomes:

> A **real-time observatory of software innovation**
