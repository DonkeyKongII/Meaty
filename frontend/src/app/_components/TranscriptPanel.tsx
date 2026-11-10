import { VirtualizedTranscriptView } from '@/components/VirtualizedTranscriptView';
import { PermissionWarning } from '@/components/PermissionWarning';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Copy, GlobeIcon } from 'lucide-react';
import { useTranscripts } from '@/contexts/TranscriptContext';
import { useConfig } from '@/contexts/ConfigContext';
import { useRecordingState } from '@/contexts/RecordingStateContext';
import { usePermissionCheck } from '@/hooks/usePermissionCheck';
import { ModalType } from '@/hooks/useModalState';
import { useIsLinux } from '@/hooks/usePlatform';
import { useMemo, useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { SpeakerAssignment } from '@/components/MeetingDetails/SpeakerAssignment';
import { SpeakerAnalysis, SpeakerTag, speakerLabel } from '@/lib/speaker-labels';

/**
 * TranscriptPanel Component
 *
 * Displays transcript content with controls for copying and language settings.
 * Uses TranscriptContext, ConfigContext, and RecordingStateContext internally.
 */

interface TranscriptPanelProps {
  // indicates stop-processing state for transcripts; derived from backend statuses.
  isProcessingStop: boolean;
  isStopping: boolean;
  showModal: (name: ModalType, message?: string) => void;
}

export function TranscriptPanel({
  isProcessingStop,
  isStopping,
  showModal
}: TranscriptPanelProps) {
  // Contexts
  const { transcripts, transcriptContainerRef, copyTranscript } = useTranscripts();
  const { transcriptModelConfig } = useConfig();
  const { isRecording, isPaused } = useRecordingState();
  const { checkPermissions, isChecking, hasSystemAudio, hasMicrophone } = usePermissionCheck();
  const isLinux = useIsLinux();

  const [liveId,setLiveId]=useState('');
  const [speakerData,setSpeakerData]=useState<SpeakerAnalysis|null>(null);
  const [target,setTarget]=useState<SpeakerTag|null>(null);
  useEffect(()=>{
    let active=true;
    if(isRecording)invoke<{live_id?:string}>('meeting_context_action',{request:{action:'live'}}).then(value=>{
      if(!active||!value.live_id)return;setLiveId(value.live_id);
      invoke<SpeakerAnalysis>('speaker_action',{meetingId:value.live_id,action:'get'}).then(data=>{if(active)setSpeakerData(data);}).catch(()=>{});
    }).catch(()=>{});
    else setTarget(null);
    return()=>{active=false;};
  },[isRecording]);
  // Convert transcripts to segments for virtualized view
  const segments = useMemo(() =>
    transcripts.map(t => ({
      id: t.id,
      timestamp: t.audio_start_time ?? 0,
      endTime: t.audio_end_time,
      text: t.text,
      confidence: t.confidence,
    })),
    [transcripts]
  );

  return (
    <div className="w-full h-full border-r border-gray-200 bg-white flex flex-col min-h-0 overflow-hidden">
      {target&&liveId&&<SpeakerAssignment key={target.id} meetingId={liveId} target={target} data={speakerData} live onSave={setSpeakerData} onClose={()=>setTarget(null)}/>}
      {/* Title area - Sticky header */}
      <div className="shrink-0 bg-white p-4 border-gray-200">
        <div className="flex flex-col space-y-3">
          <div className="flex  flex-col space-y-2">
            <div className="flex justify-center  items-center space-x-2">
              <ButtonGroup>
                {transcripts?.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={copyTranscript}
                    title="Copy Transcript"
                  >
                    <Copy />
                    <span className='hidden md:inline'>
                      Copy
                    </span>
                  </Button>
                )}
                {transcriptModelConfig.provider === "localWhisper" &&
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => showModal('languageSettings')}
                    title="Language"
                  >
                    <GlobeIcon />
                    <span className='hidden md:inline'>
                      Language
                    </span>
                  </Button>
                }
              </ButtonGroup>
            </div>
          </div>
        </div>
      </div>

      {/* Permission Warning - Not needed on Linux */}
      {!isRecording && !isChecking && !isLinux && (
        <div className="shrink-0 flex justify-center px-4 pt-4">
          <PermissionWarning
            hasMicrophone={hasMicrophone}
            hasSystemAudio={hasSystemAudio}
            onRecheck={checkPermissions}
            isRechecking={isChecking}
          />
        </div>
      )}

      {/* Transcript content - bounded flex container for virtualization */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden pb-20">
        <div className="flex justify-center flex-1 min-h-0">
          <div className="w-2/3 max-w-[750px] flex flex-col flex-1 min-h-0">
            <VirtualizedTranscriptView
              containerRef={transcriptContainerRef}
              segments={segments}
              speakerLabels={Object.fromEntries(segments.map(s=>[s.id,speakerLabel(speakerData,s.timestamp,s.endTime)]))}
              onAssignTimestamp={isRecording&&liveId?(start,end)=>{const segment=transcripts.find(t=>t.audio_start_time===start);if(segment?.audio_start_time==null)return;setTarget({id:`__span__:${start}:${end!=null&&end>start?end:start+0.5}`,name:'Unidentified speaker'});}:undefined}
              isRecording={isRecording}
              isPaused={isPaused}
              isProcessing={isProcessingStop}
              isStopping={isStopping}
              enableStreaming={isRecording}
              showConfidence={true}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
