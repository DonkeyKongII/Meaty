CREATE TABLE meeting_context (
 meeting_id TEXT PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
 data TEXT NOT NULL DEFAULT '{}', search_text TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE meeting_context_settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
INSERT INTO meeting_context_settings VALUES(1, '{"internal_domains":["hunters.ai","hunters.security","seamlesslabs.ai","s10s.ai","s10slabs.ai"],"company_names":{}}');
