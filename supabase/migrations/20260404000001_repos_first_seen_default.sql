-- Set default on repos.first_seen_date so upserts don't require it explicitly
-- (DB sets it automatically on first insert; ON CONFLICT DO UPDATE leaves it untouched)
ALTER TABLE repos ALTER COLUMN first_seen_date SET DEFAULT CURRENT_DATE;
