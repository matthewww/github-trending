-- Fix clusters.centroid dimension: 1536 → 384 to match sentence-transformers/all-MiniLM-L6-v2
ALTER TABLE clusters DROP COLUMN IF EXISTS centroid;
ALTER TABLE clusters ADD COLUMN centroid vector(384);
