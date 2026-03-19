# GitHub Trending Supabase Collector

Collects trending GitHub repositories daily via GitHub Actions and stores them in Supabase.

## Setup

### 1. Create Supabase Project
- Go to [supabase.com](https://supabase.com) and create a free project
- Note your project URL and API key

### 2. Create Database Schema
Run this SQL in your Supabase SQL editor:

```sql
create table repositories (
  id bigserial primary key,
  repo_name text not null,
  url text not null,
  description text,
  language text,
  stars integer,
  rank integer,
  collected_at timestamp default now(),
  unique(repo_name, collected_at::date)
);

create index idx_repo_date on repositories(repo_name, collected_at);
create index idx_collected_at on repositories(collected_at);
```

### 3. Set GitHub Actions Secrets
In your GitHub repo settings, add:
- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_KEY` - Your Supabase API key (use anon/public key, not service role)
- `GITHUB_TOKEN` - (auto-provided by GitHub)

### 4. Done
The workflow runs daily at 10 AM UTC. Check `.github/workflows/collect-daily.yml` to adjust the schedule.

## Structure
- `src/collect.py` - Scrapes trending repos
- `src/supabase_client.py` - Handles Supabase inserts
- `.github/workflows/collect-daily.yml` - GitHub Actions trigger

## Data
Each collection captures:
- Repository name and URL
- Description, language, star count
- Rank (position in trending list)
- Collection timestamp (deduplicated by repo + date)
