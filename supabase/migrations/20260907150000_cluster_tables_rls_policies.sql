-- Restore pipeline access to the cluster identity tables after RLS was
-- enabled on them out-of-band (Supabase dashboard, ~2026-09-07) without any
-- policies. That blocked every write for the pipeline key (anon) — inserts
-- failed with 42501, updates/deletes silently no-opped, and reads returned
-- empty — which broke cluster identity tracking and would hard-fail the next
-- weekly cluster run.
--
-- The pipeline (GitHub Actions + local scripts) authenticates with the anon
-- key, matching the posture of every other table in this project. These
-- permissive policies keep RLS enabled (security-advisor clean) while letting
-- the pipeline read and write as before.

alter table cluster_registry enable row level security;
alter table cluster_weeks    enable row level security;
alter table clusters         enable row level security;
alter table repo_cluster_map enable row level security;

drop policy if exists pipeline_all_access on cluster_registry;
drop policy if exists pipeline_all_access on cluster_weeks;
drop policy if exists pipeline_all_access on clusters;
drop policy if exists pipeline_all_access on repo_cluster_map;

create policy pipeline_all_access on cluster_registry
  for all to anon, authenticated
  using (true) with check (true);

create policy pipeline_all_access on cluster_weeks
  for all to anon, authenticated
  using (true) with check (true);

create policy pipeline_all_access on clusters
  for all to anon, authenticated
  using (true) with check (true);

create policy pipeline_all_access on repo_cluster_map
  for all to anon, authenticated
  using (true) with check (true);