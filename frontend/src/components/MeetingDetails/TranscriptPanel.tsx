"use client";

import { Transcript, TranscriptSegmentData } from '@/types';
import { TranscriptView } from '@/components/TranscriptView';
import { VirtualizedTranscriptView } from '@/components/VirtualizedTranscriptView';
import { TranscriptButtonGroup } from './TranscriptButtonGroup';
import { useMemo, useState } from 'react';
import { CombineMeetingsPanel } from './CombineMeetingsPanel';
import { MeetingContextPanel } from './MeetingContextPanel';
import {MeetingPipelineStatus} from './MeetingPipelineStatus';
import {SpeakerAssignment} from './SpeakerAssignment';
import { SpeakerPanel } from './SpeakerPanel';
import { SpeakerAnalysis, speakerLabel, speakerTags } from '@/lib/speaker-labels';

interface TranscriptPanelProps {
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
  const [speakerData, setSpeakerData] = useState<SpeakerAnalysis|null>(null);

  const [assignTarget,setAssignTarget]=useState<{id:string;name:string}|null>(null);

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
    if (!query) return convertedSegments;
    return convertedSegments.filter(segment => segment.text.toLowerCase().includes(query));
  }, [convertedSegments, searchQuery]);

  return (
    <div className="meaty-transcript flex h-full min-w-0 w-full bg-white flex-col relative @container">
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
            {searchQuery.trim() && (
              <span className="text-xs text-gray-500 whitespace-nowrap">
                {visibleSegments.length} of {convertedSegments.length}
              </span>
            )}
          </div>
        )}
      </div>

      {meetingId&&!isRecording&&<MeetingPipelineStatus meetingId={meetingId}/>}
      {meetingId && !isRecording && <CombineMeetingsPanel meetingId={meetingId}/>}
      {meetingId && !isRecording && <MeetingContextPanel meetingId={meetingId}/>}
      {meetingId && <SpeakerPanel meetingId={meetingId} disabled={isRecording} onChange={setSpeakerData}/>}

      {assignTarget&&meetingId&&<SpeakerAssignment key={`${meetingId}:${assignTarget.id}`} meetingId={meetingId} target={assignTarget} data={speakerData} onClose={()=>setAssignTarget(null)} onSave={value=>{setSpeakerData(value);window.dispatchEvent(new CustomEvent('speaker-labels-saved',{detail:{meetingId,value}}));}}/>}
      {/* Transcript content - use virtualized view for better performance */}
      <div className="flex-1 overflow-hidden pb-4">
        {searchQuery.trim() && visibleSegments.length === 0 ? (
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
    </div>
  );
}
