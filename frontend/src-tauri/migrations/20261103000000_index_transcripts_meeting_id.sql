-- Meeting loads previously full-scanned the transcripts table on every
-- meeting_id lookup; index the foreign key.
CREATE INDEX IF NOT EXISTS idx_transcripts_meeting_id ON transcripts(meeting_id);
