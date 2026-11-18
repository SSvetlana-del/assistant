-- Private schema: do not add it to Supabase Data API exposed schemas.
CREATE SCHEMA IF NOT EXISTS it_advisor;
CREATE TABLE IF NOT EXISTS it_advisor.sessions (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS it_advisor.drafts (
    token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS drafts_session_idx ON it_advisor.drafts(session_id);
CREATE TABLE IF NOT EXISTS it_advisor.enrollments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, course_id)
);
REVOKE ALL ON SCHEMA it_advisor FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA it_advisor FROM PUBLIC;
ALTER TABLE it_advisor.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE it_advisor.drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE it_advisor.enrollments ENABLE ROW LEVEL SECURITY;
