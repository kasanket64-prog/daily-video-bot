CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  status TEXT NOT NULL,
  metadata TEXT,
  file_id TEXT,
  message_id INTEGER,
  size INTEGER,
  expires INTEGER NOT NULL,
  youtube_state TEXT,
  youtube_id TEXT,
  instagram_state TEXT,
  instagram_id TEXT
);
CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
