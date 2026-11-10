-- Preserve explicit user names and calendar event names across summary generation.
ALTER TABLE meetings ADD COLUMN title_source TEXT NOT NULL DEFAULT 'legacy';

-- Recover generated titles from older builds where provenance was not recorded.
UPDATE meetings SET title_source='ai'
WHERE title_source='legacy' AND EXISTS (
 SELECT 1 FROM summary_processes s WHERE s.meeting_id=meetings.id AND json_valid(s.result)
 AND (json_extract(s.result,'$.MeetingName')=meetings.title
 OR instr(json_extract(s.result,'$.markdown'),'# ' || meetings.title || char(10))=1
 OR json_extract(s.result,'$.markdown')='# ' || meetings.title)
);
UPDATE meetings SET title=(SELECT json_extract(c.data,'$.calendar_title') FROM meeting_context c WHERE c.meeting_id=meetings.id),title_source='calendar'
WHERE (title_source='ai' OR (title_source='legacy' AND (title GLOB 'Meeting [0-9]*' OR title GLOB 'Meeting_[0-9]*' OR title IN ('','+ New Call','Untitled','Untitled Meeting'))))
AND EXISTS (SELECT 1 FROM meeting_context c WHERE c.meeting_id=meetings.id AND length(trim(COALESCE(json_extract(c.data,'$.calendar_title'),'')))>0);
