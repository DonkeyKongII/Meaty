"use client";

import { Transcript, TranscriptSegmentData } from '@/types';
import { TranscriptView } from '@/components/TranscriptView';
import { VirtualizedTranscriptView } from '@/components/VirtualizedTranscriptView';
import { TranscriptButtonGroup } from './TranscriptButtonGroup';
import { useMemo, useState } from 'react';
import { CombineMeetingsPanel } from './CombineMeetingsPanel';
import { MeetingContextPanel } from './MeetingContextPanel';
import {MeetingPipelineStatus} from './MeetingPipelineStatus';
import {invoke} from '@tauri-apps/api/core';
import {useEffect} from 'react';
import {useSidebar} from '@/components/Sidebar/SidebarProvider';
import {SpeakerAssignment} from './SpeakerAssignment';
import { SpeakerPanel } from './SpeakerPanel';
import { SpeakerAnalysis, SpeakerTag, speakerLabel, speakerTags, groupedSpeakers } from '@/lib/speaker-labels';

interface TranscriptPanelProps {
  meetingTitle?: string;
  onTitleChange?: (title:string)=>void;
  transcripts: Transcript[];
  customPrompt: string;
  onPromptChange: (value: string) => void;
  onCopyTranscript: () => void;
  onOpenMeetingFolder: () => Promise<void>;
  isRecording: boolean;
  disableAutoScroll?: boolean;

  // Optional pagination props (when using virtualization)
  usePagination?: boolean;
  segments?: TranscriptSegmentData[];
  hasMore?: boolean;
  isLoadingMore?: boolean;
  totalCount?: number;
  loadedCount?: number;
  onLoadMore?: () => void;

  // Retranscription props
  meetingId?: string;
  meetingFolderPath?: string | null;
  onRefetchTranscripts?: () => Promise<void>;
}

export function TranscriptPanel({
  transcripts,
  meetingTitle,
  onTitleChange,
  customPrompt,
  onPromptChange,
  onCopyTranscript,
  onOpenMeetingFolder,
  isRecording,
  disableAutoScroll = false,
  usePagination = false,
  segments,
  hasMore,
  isLoadingMore,
  totalCount,
  loadedCount,
  onLoadMore,
  meetingId,
  meetingFolderPath,
  onRefetchTranscripts,
}: TranscriptPanelProps) {
  const [view,setView]=useState<'details'|'transcript'>('details');
  const [speakerFilter,setSpeakerFilter]=useState('all');
  const [titleDraft,setTitleDraft]=useState(meetingTitle||'');
  const [titleBusy,setTitleBusy]=useState(false);
  const [titleError,setTitleError]=useState('');
  const {refetchMeetings}=useSidebar();
  useEffect(()=>{setTitleDraft(meetingTitle||'');},[meetingTitle]);
  useEffect(()=>{setView('details');setSpeakerFilter('all');setSearchQuery('');},[meetingId]);
  async function saveTitle(){if(!meetingId||!titleDraft.trim())return;setTitleBusy(true);setTitleError('');try{await invoke('api_save_meeting_title',{meetingId,title:titleDraft.trim()});onTitleChange?.(titleDraft.trim());await refetchMeetings();}catch(e){setTitleError(String(e));}finally{setTitleBusy(false);}}
  const [speakerData, setSpeakerData] = useState<SpeakerAnalysis|null>(null);

  const [assignTarget,setAssignTarget]=useState<SpeakerTag|null>(null);

  // In-meeting transcript search: filters the visible segments to matches.
  const [searchQuery, setSearchQuery] = useState('');

  // Convert transcripts to segments if pagination is not used but we want virtualization
  const convertedSegments = useMemo(() => {
    if (usePagination && segments) {
      return segments;
    }
    // Convert transcripts to segments for virtualization
    return transcripts.map(t => ({
      id: t.id,
      timestamp: t.audio_start_time ?? 0,
      audioTimestampKnown: t.audio_start_time != null,
      endTime: t.audio_end_time,
      text: t.text,
      confidence: t.confidence,
    }));
  }, [transcripts, usePagination, segments]);

  const visibleSegments = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return convertedSegments.filter(segment => {
      if(query&&!segment.text.toLowerCase().includes(query))return false;
      if(speakerFilter==='all')return true;
      const tags=speakerTags(speakerData,segment.timestamp,segment.endTime);
      return tags.some(tag=>{const voice=speakerData?.speakers.find(s=>s.id===tag.id);return speakerFilter==='unresolved'?!voice||voice.status==='unknown':(voice?.profile_id||voice?.name.trim().toLocaleLowerCase())===speakerFilter;});
    });
  }, [convertedSegments, searchQuery, speakerFilter, speakerData]);

  return (
    <div className="meaty-transcript flex h-full min-w-0 w-full bg-white flex-col relative @container">
      <div className="meaty-meeting-tabs" role="tablist" aria-label="Meeting panel">
        <button type="button" role="tab" id="meeting-details-tab" aria-controls="meeting-details-pane" aria-selected={view==='details'} onClick={()=>setView('details')}>Meeting Details</button>
        <button type="button" role="tab" id="meeting-transcript-tab" aria-controls="meeting-transcript-pane" aria-selected={view==='transcript'} onClick={()=>setView('transcript')}>Transcript</button>
      </div>
      {meetingId&&!isRecording&&<MeetingPipelineStatus meetingId={meetingId} onComplete={onRefetchTranscripts}/>}
      <section id="meeting-details-pane" role="tabpanel" aria-labelledby="meeting-details-tab" hidden={view!=='details'} className="flex-1 overflow-y-auto">
        <div className="p-4 border-b space-y-2">
          <label htmlFor="meeting-name" className="meaty-panel-label">Meeting name</label>
          <form className="flex flex-wrap gap-2" onSubmit={e=>{e.preventDefault();void saveTitle();}}><input id="meeting-name" className="min-w-0 flex-1 border p-2" value={titleDraft} onChange={e=>setTitleDraft(e.target.value)}/><button disabled={titleBusy||!titleDraft.trim()||titleDraft===meetingTitle} className="meaty-action" type="submit">{titleBusy?'Saving…':'Save'}</button></form>
          {titleError&&<p role="alert">{titleError}</p>}
        </div>
        {meetingId&&!isRecording&&<MeetingContextPanel meetingId={meetingId} onTitleChange={onTitleChange}/>}
        {meetingId&&<SpeakerPanel meetingId={meetingId} disabled={isRecording} onChange={setSpeakerData}/>}
        {meetingId&&!isRecording&&<details className="p-4 border-t"><summary>More meeting actions</summary><CombineMeetingsPanel meetingId={meetingId}/></details>}
      </section>
      <section id="meeting-transcript-pane" role="tabpanel" aria-labelledby="meeting-transcript-tab" hidden={view!=='transcript'} className="flex flex-1 min-h-0 flex-col">
      {/* Title area */}
      <div className="meaty-toolbar p-4 border-b border-gray-200">
        <h2 className="meaty-panel-label">The conversation</h2>
        <TranscriptButtonGroup
          transcriptCount={usePagination ? (totalCount ?? convertedSegments.length) : (transcripts?.length || 0)}
          onCopyTranscript={onCopyTranscript}
          onOpenMeetingFolder={onOpenMeetingFolder}
          meetingId={meetingId}
          meetingFolderPath={meetingFolderPath}
          onRefetchTranscripts={onRefetchTranscripts}
        />
        {convertedSegments.length > 0 && (
          <div className="mt-3 flex items-center gap-2">
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search this transcript…"
              aria-label="Search this transcript"
              className="flex-1 min-w-0 px-3 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
            />
            <select aria-label="Filter by speaker" value={speakerFilter} onChange={e=>setSpeakerFilter(e.target.value)} className="min-w-0 max-w-[45%] border p-2 text-sm">
              <option value="all">All speakers</option>
              {groupedSpeakers(speakerData).known.map(group=><option key={group[0].id} value={group[0].profile_id||group[0].name.trim().toLocaleLowerCase()}>{group[0].name}</option>)}
              <option value="unresolved">Unidentified speakers</option>
            </select>
            {searchQuery.trim() && (
              <span className="text-xs text-gray-500 whitespace-nowrap">
                {visibleSegments.length} of {convertedSegments.length}
              </span>
            )}
          </div>
        )}
      </div>



      {assignTarget&&meetingId&&<SpeakerAssignment key={`${meetingId}:${assignTarget.id}`} meetingId={meetingId} target={assignTarget} data={speakerData} onClose={()=>setAssignTarget(null)} onSave={value=>{setSpeakerData(value);window.dispatchEvent(new CustomEvent('speaker-labels-saved',{detail:{meetingId,value}}));}}/>}
      {/* Transcript content - use virtualized view for better performance */}
      <div className="flex-1 overflow-hidden pb-4">
        {(searchQuery.trim()||speakerFilter!=='all') && visibleSegments.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center p-8 text-sm text-gray-500 text-center">
            <p>No matches in the {convertedSegments.length} loaded segments{hasMore && totalCount ? ` of ${totalCount}` : ''}.</p>
            {hasMore && onLoadMore && (
              <button
                onClick={onLoadMore}
                disabled={isLoadingMore}
                className="mt-3 px-3 py-1.5 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {isLoadingMore ? 'Loading…' : 'Load earlier segments to keep searching'}
              </button>
            )}
          </div>
        ) : (
        <VirtualizedTranscriptView
          segments={visibleSegments}
          onAssignSpeaker={meetingId&&!isRecording&&!['queued','running'].includes(speakerData?.job_status||'')?setAssignTarget:undefined}
          speakerTags={meetingId&&!isRecording?Object.fromEntries(convertedSegments.map(segment=>[segment.id,speakerTags(speakerData,segment.timestamp,segment.endTime)])):undefined}
          speakerLabels={Object.fromEntries(convertedSegments.map(segment => [segment.id, segment.audioTimestampKnown === false ? undefined : speakerLabel(speakerData, segment.timestamp, segment.endTime)]))}
          isRecording={isRecording}
          isPaused={false}
          isProcessing={false}
          isStopping={false}
          enableStreaming={false}
          showConfidence={true}
          disableAutoScroll={disableAutoScroll}
          hasMore={hasMore}
          isLoadingMore={isLoadingMore}
          totalCount={totalCount}
          loadedCount={loadedCount}
          onLoadMore={onLoadMore}
        />
        )}
      </div>

      {/* Custom prompt input at bottom of transcript section */}
      {!isRecording && convertedSegments.length > 0 && (
        <div className="p-1 border-t border-gray-200">
          <textarea
            placeholder="Add context for AI summary. For example people involved, meeting overview, objective etc..."
            className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 bg-white shadow-sm min-h-[80px] resize-y"
            value={customPrompt}
            onChange={(e) => onPromptChange(e.target.value)}
          />
        </div>
      )}
      </section>
    </div>
  );
}
