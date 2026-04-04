-- Phase 2: Resize embeddings from 1536-dim to 384-dim (sentence-transformers/all-MiniLM-L6-v2)
-- Add cluster evolution tracking and UMAP 2D scatter coordinates

-- Drop and recreate embeddings with correct dimension
ALTER TABLE embeddings DROP COLUMN IF EXISTS embedding;
ALTER TABLE embeddings ADD COLUMN embedding vector(384);

-- Cluster evolution: link to prior week's cluster
ALTER TABLE clusters
  ADD COLUMN IF NOT EXISTS prev_cluster_id bigint REFERENCES clusters(id),
  ADD COLUMN IF NOT EXISTS description text;

-- UMAP 2D coords for dashboard scatter plot
ALTER TABLE repo_cluster_map
  ADD COLUMN IF NOT EXISTS umap_x float,
  ADD COLUMN IF NOT EXISTS umap_y float;
