-- Cluster identity layer: stable keys, weekly history, and per-repo migration tracking.
-- Enables cluster-level trends (emergence, growth, splits/merges) across weekly re-clustering.

-- Stable cluster identity: one row per semantic cluster ever seen.
-- cluster_key is a slug derived from the label at birth and never changes.
create table if not exists cluster_registry (
  cluster_key  text primary key,
  label        text not null,
  description  text,
  first_seen   date not null,
  last_seen    date not null,
  weeks_seen   integer not null default 1,
  status       text not null default 'active'  -- active | retired
);

-- Weekly size history per stable cluster (streamgraph / growth trends).
create table if not exists cluster_weeks (
  cluster_key  text not null references cluster_registry(cluster_key),
  week         date not null,
  size         integer not null,
  primary key (cluster_key, week)
);

create index if not exists cluster_weeks_week_idx on cluster_weeks (week);

-- Link each weekly clustering run to its stable identity.
alter table clusters
  add column if not exists cluster_key text references cluster_registry(cluster_key);

-- Per-repo stable assignment + candidate key (2-week rule before migrating).
alter table repo_cluster_map
  add column if not exists stable_cluster_key text,
  add column if not exists candidate_cluster_key text;
