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

**Tables:**

#### repositories

* id
* name
* description
* metadata (JSONB)

#### time_series_metrics

* repo_id
* date
* stars
* forks
* contributors
* commits

#### embeddings

* repo_id
* vector (pgvector)

#### tags

* repo_id
* tags (JSONB)

#### clusters

* cluster_id
* centroid vector
* label (optional)

#### repo_cluster_map

* repo_id
* cluster_id
* timestamp

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
* **Database:** Supabase (Postgres + pgvector)
* **Embeddings:** OpenAI or local models
* **Clustering:** HDBSCAN + UMAP
* **Frontend:**

  * Short-term: Plotly / notebooks
  * Long-term: React + D3 / ECharts

---

## 10. Phased Implementation Plan

### Phase 1 – Foundation

* Ingest GitHub trending data
* Store repo + time-series data
* Basic visualisations (stars, growth)

---

### Phase 2 – Semantic Layer

* Add embeddings
* Add LLM-generated tags
* Basic clustering

---

### Phase 3 – Trend Intelligence

* Track cluster growth
* Build cluster-level dashboards
* Add novelty detection

---

### Phase 4 – Advanced Insights

* Cluster evolution (split/merge detection)
* Tag graph analysis
* Predictive trend signals

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

> Currently only `daily` is collected. Calling all three periods per run would triple signal density immediately with no extra auth or tooling.

#### GitHub REST API (auth: `GITHUB_TOKEN`, 5,000 req/hr authenticated)

```
GET https://api.github.com/repos/{owner}/{repo}         # metadata: description, topics, owner type
GET https://api.github.com/repos/{owner}/{repo}/readme  # README content (base64-encoded)
```

#### GitHub Models API (auth: `GH_MODELS_TOKEN`)

```
POST https://models.inference.ai.azure.com/chat/completions
```

### Existing Dataset (reusable for bootstrapping)

| Table | Rows | Content |
|-------|------|---------|
| `repositories` | 372 | Daily trending scrapes since ~Feb 17, 2026 — repo name, description, language, stars\_today, total\_stars, forks, rank, collected\_date |
| `repo_insights` | 69 | LLM-generated per-repo: purpose, category, key\_themes, creator\_type, creator\_description, target\_audience |
| `weekly_digest` | 2 | Prose digests with headline, emerging\_themes, top\_categories |

This dataset is immediately usable for bootstrapping embeddings and testing clustering in the new project.

### What the Prior Project Already Built

| Component | Status |
|-----------|--------|
| Daily trending scraper | ✅ Production |
| Supabase storage + deduplication | ✅ Production |
| LLM enrichment (purpose, category, key\_themes) | ✅ Production |
| Creator connection tracking | ✅ Production |
| Weekly prose digest generation | ✅ Production |
| Static dashboard (charts + digest display) | ✅ Production |
| Vector embeddings | ❌ Not started |
| Clustering (HDBSCAN/UMAP) | ❌ Not started |
| Cluster-level trend detection | ❌ Not started |
| Novelty detection | ❌ Not started |
| Cluster map visualisation | ❌ Not started |

---

## 17. Summary

This system shifts from:

* Static categorisation → Dynamic mapping
* Repo-level metrics → Idea-level trends
* Snapshot views → Evolution over time

If executed well, it becomes:

> A **real-time observatory of software innovation**
