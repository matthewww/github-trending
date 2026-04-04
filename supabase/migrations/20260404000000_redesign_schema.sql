-- Redesign schema: split repositories into owners + repos + trending_snapshots
-- Add embeddings, clusters, repo_cluster_map for Phase 2
-- Enable pgvector

CREATE EXTENSION IF NOT EXISTS vector;

DROP VIEW IF EXISTS today_trending;

-- ============================================================
-- OWNERS
-- ============================================================
CREATE TABLE owners (
  owner_name   TEXT PRIMARY KEY,
  owner_type   TEXT,    -- individual | startup | big_tech | academic | open_source_org
  description  TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

INSERT INTO owners (owner_name, owner_type, description)
SELECT DISTINCT ON (split_part(repo_name, '/', 1))
  split_part(repo_name, '/', 1),
  creator_type,
  creator_description
FROM repo_insights
ORDER BY split_part(repo_name, '/', 1), analyzed_at DESC
ON CONFLICT (owner_name) DO NOTHING;

INSERT INTO owners (owner_name)
SELECT DISTINCT split_part(repo_name, '/', 1)
FROM repositories
WHERE split_part(repo_name, '/', 1) NOT IN (SELECT owner_name FROM owners)
ON CONFLICT (owner_name) DO NOTHING;

-- ============================================================
-- REPOS
-- ============================================================
CREATE TABLE repos (
  repo_name        TEXT PRIMARY KEY,
  owner_name       TEXT NOT NULL REFERENCES owners(owner_name),
  description      TEXT,
  language         TEXT,
  topics           TEXT[],
  first_seen_date  DATE,
  created_at       TIMESTAMPTZ DEFAULT now(),
  updated_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX repos_owner_idx    ON repos (owner_name);
CREATE INDEX repos_language_idx ON repos (language);

INSERT INTO repos (repo_name, owner_name, description, language, first_seen_date)
SELECT
  repo_name,
  split_part(repo_name, '/', 1),
  description,
  language,
  first_seen
FROM (
  SELECT DISTINCT ON (repo_name)
    repo_name,
    description,
    language,
    MIN(collected_date) OVER (PARTITION BY repo_name) AS first_seen
  FROM repositories
  ORDER BY repo_name, collected_date DESC
) sub
ON CONFLICT (repo_name) DO NOTHING;

-- ============================================================
-- TRENDING_SNAPSHOTS
-- ============================================================
CREATE TABLE trending_snapshots (
  id               BIGSERIAL PRIMARY KEY,
  repo_name        TEXT NOT NULL REFERENCES repos(repo_name),
  collected_date   DATE NOT NULL,
  since_period     TEXT NOT NULL DEFAULT 'daily',  -- daily | weekly | monthly
  stars_in_period  INTEGER,
  total_stars      INTEGER,
  forks            INTEGER,
  rank             INTEGER,
  collected_at     TIMESTAMPTZ DEFAULT now(),
  UNIQUE (repo_name, collected_date, since_period)
);

CREATE INDEX snapshots_date_idx   ON trending_snapshots (collected_date DESC);
CREATE INDEX snapshots_repo_idx   ON trending_snapshots (repo_name);
CREATE INDEX snapshots_period_idx ON trending_snapshots (since_period);

INSERT INTO trending_snapshots
  (repo_name, collected_date, since_period, stars_in_period, total_stars, forks, rank, collected_at)
SELECT
  repo_name, collected_date, 'daily', stars_today, total_stars, forks, rank, COALESCE(collected_at, now())
FROM repositories
ON CONFLICT (repo_name, collected_date, since_period) DO NOTHING;

-- ============================================================
-- REPO_INSIGHTS (update in place)
-- ============================================================
ALTER TABLE repo_insights
  DROP COLUMN IF EXISTS creator_name,
  DROP COLUMN IF EXISTS creator_type,
  DROP COLUMN IF EXISTS creator_description,
  DROP COLUMN IF EXISTS creator_prior_repos;

ALTER TABLE repo_insights
  ADD CONSTRAINT repo_insights_repo_fk
  FOREIGN KEY (repo_name) REFERENCES repos(repo_name)
  NOT VALID;

-- ============================================================
-- EMBEDDINGS
-- ============================================================
CREATE TABLE embeddings (
  repo_name    TEXT PRIMARY KEY REFERENCES repos(repo_name),
  embedding    vector(1536),
  source_text  TEXT,
  model_used   TEXT,
  generated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- CLUSTERS
-- ============================================================
CREATE TABLE clusters (
  id          BIGSERIAL PRIMARY KEY,
  run_date    DATE NOT NULL,
  label       TEXT,
  size        INTEGER,
  centroid    vector(1536),
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX clusters_run_date_idx ON clusters (run_date DESC);

-- ============================================================
-- REPO_CLUSTER_MAP
-- ============================================================
CREATE TABLE repo_cluster_map (
  repo_name   TEXT NOT NULL REFERENCES repos(repo_name),
  cluster_id  BIGINT NOT NULL REFERENCES clusters(id),
  run_date    DATE NOT NULL,
  PRIMARY KEY (repo_name, run_date)
);

CREATE INDEX repo_cluster_map_cluster_idx ON repo_cluster_map (cluster_id);

-- ============================================================
-- VIEWS
-- ============================================================
CREATE OR REPLACE VIEW today_trending AS
SELECT
  s.repo_name,
  r.description,
  r.language,
  r.owner_name,
  s.stars_in_period AS stars_today,
  s.total_stars,
  s.forks,
  s.rank,
  s.since_period,
  s.collected_date
FROM trending_snapshots s
JOIN repos r USING (repo_name)
WHERE s.collected_date = CURRENT_DATE
ORDER BY s.since_period, s.rank;

CREATE OR REPLACE VIEW repos_needing_insights AS
SELECT r.repo_name, r.description, r.language, r.first_seen_date
FROM repos r
LEFT JOIN repo_insights i USING (repo_name)
WHERE i.repo_name IS NULL
ORDER BY r.first_seen_date;

-- ============================================================
-- RLS
-- ============================================================
ALTER TABLE owners             ENABLE ROW LEVEL SECURITY;
ALTER TABLE repos              ENABLE ROW LEVEL SECURITY;
ALTER TABLE trending_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE clusters           ENABLE ROW LEVEL SECURITY;
ALTER TABLE repo_cluster_map   ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON owners             FOR SELECT USING (true);
CREATE POLICY "Public read" ON repos              FOR SELECT USING (true);
CREATE POLICY "Public read" ON trending_snapshots FOR SELECT USING (true);
CREATE POLICY "Public read" ON embeddings         FOR SELECT USING (true);
CREATE POLICY "Public read" ON clusters           FOR SELECT USING (true);
CREATE POLICY "Public read" ON repo_cluster_map   FOR SELECT USING (true);

DROP TABLE repositories;
