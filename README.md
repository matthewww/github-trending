# GitHub Trending Insights

Collects trending GitHub repositories daily via GitHub Actions and stores them in Supabase.

[View on GitHub Pages](https://matthewww.github.io/github-trending/)

![Site preview](site.png)

## What it does

- Scrapes GitHub Trending (daily / weekly / monthly) each day at 10:00 UTC
- Stores repos, owners, and time-series snapshots in Supabase (Postgres + pgvector)
- Enriches each repo with LLM-generated purpose, category, and key themes via GitHub Models (`gpt-4o-mini`)
- Generates a weekly prose digest every Sunday
- Exports a static `snapshot.json` and deploys a GitHub Pages dashboard

## Roadmap

| Phase | Status | Focus |
|---|---|---|
| **1 — Foundation** | ✅ Complete | Scraper, storage, LLM enrichment, weekly digest, static dashboard with archive |
| **2 — Semantic Layer** | 🔲 Next | Embeddings (`text-embedding-3-small`), HDBSCAN clustering, cluster labelling via LLM |
| **3 — Trend Intelligence** | 🔲 Planned | Cluster growth tracking, novelty detection, cluster map view in dashboard |
| **4 — Advanced Insights** | 🔲 Future | Cluster evolution (split/merge), tag graph analysis, breakout alerts |

See [`prd-brainstorm-29_03_26/prd.md`](prd-brainstorm-29_03_26/prd.md) for full implementation detail.

## Stack

- **Pipeline:** Python 3.11, GitHub Actions
- **Database:** Supabase (Postgres 17 + pgvector), `eu-west-1`
- **LLM:** GitHub Models API (`gpt-4o-mini`) — chat; OpenAI `text-embedding-3-small` — embeddings (Phase 2)
- **Dashboard:** Vanilla JS SPA, Chart.js, GitHub Pages — no build step
