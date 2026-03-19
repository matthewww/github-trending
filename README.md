# GitHub Trending Supabase Collector

Collects trending GitHub repositories daily via GitHub Actions and stores them in Supabase.

## Setup

### 1. Create Supabase Project
- Go to [supabase.com](https://supabase.com) and create a free project
- Note your project URL and API key

### 2. Create Database Schema
Apply the migration using the Supabase CLI:

```bash
supabase db push
```

Or paste the contents of `supabase/migrations/20260319193622_new-migration.sql` directly into the Supabase SQL editor.

### 3. Set GitHub Actions Secrets
In your GitHub repo settings, add:
- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_KEY` - Your Supabase Secret key (service role key) — required if RLS is not enabled
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
