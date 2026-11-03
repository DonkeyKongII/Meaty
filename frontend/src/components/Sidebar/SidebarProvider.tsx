'use client';

import React, { createContext, useContext, useState, useEffect, useMemo, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { companionOwnsRecording } from '@/lib/meeting-recording';
import Analytics from '@/lib/analytics';
import { invoke } from '@tauri-apps/api/core';
import { useRecordingState } from '@/contexts/RecordingStateContext';
import type { SummaryProcessResponse } from '@/types';



interface SidebarItem {
  id: string;
  title: string;
  type: 'folder' | 'file';
  children?: SidebarItem[];
}

export interface CurrentMeeting {
  id: string;
  title: string;
  companies?: string[];
}

// Search result type for transcript search
interface TranscriptSearchResult {
  id: string;
  title: string;
  matchContext: string;
  timestamp: string;
}

interface SummaryPoll {
  processId: string;
  timer: NodeJS.Timeout;
  inFlight: boolean;
}

interface SidebarContextType {
  currentMeeting: CurrentMeeting | null;
  setCurrentMeeting: (meeting: CurrentMeeting | null) => void;
  sidebarItems: SidebarItem[];
  isCollapsed: boolean;
  toggleCollapse: () => void;
  meetings: CurrentMeeting[];
  setMeetings: (meetings: CurrentMeeting[]) => void;
  isMeetingActive: boolean;
  setIsMeetingActive: (active: boolean) => void;
  handleRecordingToggle: () => void;
  searchTranscripts: (query: string) => Promise<void>;
  searchResults: TranscriptSearchResult[];
  isSearching: boolean;
  setServerAddress: (address: string) => void;
  serverAddress: string;
  transcriptServerAddress: string;
  setTranscriptServerAddress: (address: string) => void;
  // Summary polling management
  startSummaryPolling: (
    meetingId: string,
    processId: string,
    onUpdate: (result: SummaryProcessResponse) => void | Promise<void>
  ) => void;
  stopSummaryPolling: (meetingId: string, processId?: string) => void;
  // Refetch meetings from backend
  refetchMeetings: () => Promise<void>;

}

const SidebarContext = createContext<SidebarContextType | null>(null);

export const useSidebar = () => {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error('useSidebar must be used within a SidebarProvider');
  }
  return context;
};

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [currentMeeting, setCurrentMeeting] = useState<CurrentMeeting | null>({ id: 'intro-call', title: '+ New Call' });
  const [isCollapsed, setIsCollapsed] = useState(true);
  const [meetings, setMeetings] = useState<CurrentMeeting[]>([]);
  const [sidebarItems, setSidebarItems] = useState<SidebarItem[]>([]);
  const [isMeetingActive, setIsMeetingActive] = useState(false);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [serverAddress, setServerAddress] = useState('');
  const [transcriptServerAddress, setTranscriptServerAddress] = useState('');
  const summaryPollsRef = React.useRef(new Map<string, SummaryPoll>());

  // Use recording state from RecordingStateContext (single source of truth)
  const { isRecording } = useRecordingState();

  const pathname = usePathname();
  const router = useRouter();

  // Extract fetchMeetings as a reusable function
  const fetchMeetings = React.useCallback(async () => {
    if (serverAddress) {
      try {
        const meetings = await invoke('api_get_meetings') as Array<{ id: string, title: string }>;
        const contexts = await invoke<Record<string, any>>('meeting_context_action', {request:{action:'list'}});
        const transformedMeetings = meetings.map((meeting: any) => ({
          id: meeting.id,
          title: meeting.title,
          companies: contexts[meeting.id]?.classification === 'internal' ? ['Internal'] : contexts[meeting.id]?.companies?.map((c:any)=>c.name) || []
        }));
        setMeetings(transformedMeetings);
        Analytics.trackBackendConnection(true);
      } catch (error) {
        console.error('Error fetching meetings:', error);
        setMeetings([]);
        Analytics.trackBackendConnection(false, error instanceof Error ? error.message : 'Unknown error');
      }
    }
  }, [serverAddress]);

  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;
    const start = () => {
      if (timer) clearInterval(timer);
      fetchMeetings();
      timer = setInterval(fetchMeetings, 15000);
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        start();
      } else {
        stop();
      }
    };
    if (document.visibilityState === 'visible') {
      start();
    }
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [serverAddress, fetchMeetings]);

  useEffect(() => {
    const fetchSettings = async () => {
      setServerAddress('http://localhost:5167');
      setTranscriptServerAddress('http://127.0.0.1:8178/stream');
    };
    fetchSettings();
  }, []);

  const companyGroups = new Map<string, CurrentMeeting[]>();
  meetings.forEach(meeting => {
    const groups = meeting.companies?.length ? meeting.companies : ['Unclassified'];
    groups.forEach(group => companyGroups.set(group, [...(companyGroups.get(group) || []), meeting]));
  });
  const baseItems: SidebarItem[] = [
    {
      id: 'meetings',
      title: 'Meeting Notes',
      type: 'folder' as const,
      children: [
        ...Array.from(companyGroups).sort(([a],[b])=>a.localeCompare(b)).map(([company, items]) => ({
          id: `company:${company}`, title: company, type: 'folder' as const,
          children: items.map(meeting => ({id:meeting.id,title:meeting.title,type:'file' as const}))
        }))
      ]
    },
  ];


  const toggleCollapse = () => {
    setIsCollapsed(!isCollapsed);
  };

  // Update current meeting when on home page
  useEffect(() => {
    if (pathname === '/') {
      setCurrentMeeting({ id: 'intro-call', title: '+ New Call' });
    }
    setSidebarItems(baseItems);
  }, [pathname]);

  // Update sidebar items when meetings change
  useEffect(() => {
    setSidebarItems(baseItems);
  }, [meetings]);

  // Function to handle recording toggle from sidebar
  const handleRecordingToggle = () => {
    if (!isRecording) {
      // Check if already on home page
      if (pathname === '/') {
        // Already on home - trigger recording directly via custom event
        console.log('Triggering recording from sidebar (already on home page)');
        window.dispatchEvent(new CustomEvent('start-recording-from-sidebar'));
      } else {
        // Not on home - navigate and use auto-start mechanism
        console.log('Navigating to home page with auto-start flag');
        sessionStorage.setItem('autoStartRecording', 'true');
        router.push('/');
      }

      // Track recording initiation from sidebar
      Analytics.trackButtonClick('start_recording', 'sidebar');
    } else {
      // While recording, the sidebar button is the always-available Stop
      // control: on Home it stops directly, elsewhere it navigates Home first
      // (the Home recording flow owns the actual stop).
      if (pathname === '/') {
        window.dispatchEvent(new CustomEvent('stop-recording-from-meeting'));
      } else {
        router.push('/');
      }
      Analytics.trackButtonClick('stop_recording', 'sidebar');
    }
    // The actual recording start/stop is handled in the Home component
  };

  // Consume bridge requests only after the frontend has mounted. Reuse the
  // normal recording flow so model/device validation and UI state stay intact.
  // A start that arrives while the previous companion-owned recording is still
  // shutting down (rejoin inside the drain window) is remembered and fired
  // once recording actually stops, instead of being silently dropped.
  const pendingRestartRef = useRef<number>(0);
  useEffect(() => {
    let busy = false;
    const timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const requested = await invoke<string>('take_meeting_autostart');
        if (requested === 'stop' && companionOwnsRecording() && isRecording) {
          if (pathname !== '/') router.push('/');
          else window.dispatchEvent(new CustomEvent('stop-recording-from-meeting'));
        }
        if (requested === 'start') {
          if (!isRecording) {
            sessionStorage.setItem('meetilyCompanionStart', 'true');
            if (pathname === '/') {
              window.dispatchEvent(new CustomEvent('start-recording-from-sidebar'));
            } else {
              sessionStorage.setItem('autoStartRecording', 'true');
              router.push('/');
            }
          } else if (companionOwnsRecording()) {
            pendingRestartRef.current = Date.now();
          }
        }
      } catch (error) {
        console.error('Meeting detection bridge:', error);
      } finally { busy = false; }
    }, 1000);
    return () => clearInterval(timer);
  }, [isRecording, pathname, router]);

  // Fire a remembered restart once the shutdown has completed (45s TTL).
  useEffect(() => {
    if (isRecording || !pendingRestartRef.current) return;
    if (Date.now() - pendingRestartRef.current > 45_000) {
      pendingRestartRef.current = 0;
      return;
    }
    pendingRestartRef.current = 0;
    sessionStorage.setItem('meetilyCompanionStart', 'true');
    if (pathname === '/') {
      window.dispatchEvent(new CustomEvent('start-recording-from-sidebar'));
    } else {
      sessionStorage.setItem('autoStartRecording', 'true');
      router.push('/');
    }
  }, [isRecording, pathname, router]);

  // Function to search through meeting transcripts
  const searchTranscripts = async (query: string) => {
    if (!query.trim()) {
      setSearchResults([]);
      return;
    }

    try {
      setIsSearching(true);


      const results = await invoke('api_search_transcripts', { query }) as TranscriptSearchResult[];
      setSearchResults(results);
    } catch (error) {
      console.error('Error searching transcripts:', error);
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  // Summary polling management
  const stopSummaryPolling = React.useCallback((meetingId: string, processId?: string) => {
    const poll = summaryPollsRef.current.get(meetingId);
    if (!poll || (processId && poll.processId !== processId)) {
      return;
    }
    clearInterval(poll.timer);
    summaryPollsRef.current.delete(meetingId);
  }, []);

  const startSummaryPolling = React.useCallback((
    meetingId: string,
    processId: string,
    onUpdate: (result: SummaryProcessResponse) => void | Promise<void>
  ) => {
    stopSummaryPolling(meetingId);
    let pollCount = 0;
    const maxPolls = 200;
    const poll = async () => {
      const entry = summaryPollsRef.current.get(meetingId);
      if (!entry || entry.processId !== processId || entry.inFlight) {
        return;
      }
      entry.inFlight = true;
      try {
        pollCount += 1;
        if (pollCount >= maxPolls) {
          await onUpdate({
            status: 'error',
            meetingName: null,
            meeting_id: meetingId,
            start: processId,
            end: null,
            data: null,
            error: 'Summary generation timed out after 15 minutes. Please try again or check your model configuration.',
          });
          if (summaryPollsRef.current.get(meetingId) === entry) {
            stopSummaryPolling(meetingId, processId);
          }
          return;
        }

        const result = await invoke<SummaryProcessResponse>('api_get_summary', { meetingId });
        const current = summaryPollsRef.current.get(meetingId);
        if (current !== entry || result.start !== processId) {
          return;
        }
        await onUpdate(result);
        if (summaryPollsRef.current.get(meetingId) !== entry) return;
        if (
          result.status === 'completed'
          || result.status === 'error'
          || result.status === 'failed'
          || result.status === 'cancelled'
          || (result.status === 'idle' && pollCount > 1)
        ) {
          stopSummaryPolling(meetingId, processId);
        }
      } catch (error) {
        const current = summaryPollsRef.current.get(meetingId);
        if (current !== entry) {
          return;
        }
        try {
          await onUpdate({
            status: 'error',
            meetingName: null,
            meeting_id: meetingId,
            start: processId,
            end: null,
            data: null,
            error: error instanceof Error ? error.message : 'Unknown error',
          });
        } catch (callbackError) {
          console.error('Failed to handle summary polling error:', callbackError);
        } finally {
          if (summaryPollsRef.current.get(meetingId) === entry) {
            stopSummaryPolling(meetingId, processId);
          }
        }
      } finally {
        const current = summaryPollsRef.current.get(meetingId);
        if (current === entry) {
          current.inFlight = false;
        }
      }
    };

    const timer = setInterval(() => void poll(), 5000);
    summaryPollsRef.current.set(meetingId, { processId, timer, inFlight: false });
  }, [stopSummaryPolling]);

  useEffect(() => () => {
    summaryPollsRef.current.forEach(({ timer }) => clearInterval(timer));
    summaryPollsRef.current.clear();
  }, []);



  const contextValue = useMemo(() => ({
    currentMeeting,
    setCurrentMeeting,
    sidebarItems,
    isCollapsed,
    toggleCollapse,
    meetings,
    setMeetings,
    isMeetingActive,
    setIsMeetingActive,
    handleRecordingToggle,
    searchTranscripts,
    searchResults,
    isSearching,
    setServerAddress,
    serverAddress,
    transcriptServerAddress,
    setTranscriptServerAddress,
    startSummaryPolling,
    stopSummaryPolling,
    refetchMeetings: fetchMeetings,
  }), [
    currentMeeting,
    sidebarItems,
    isCollapsed,
    toggleCollapse,
    meetings,
    isMeetingActive,
    handleRecordingToggle,
    searchTranscripts,
    searchResults,
    isSearching,
    serverAddress,
    transcriptServerAddress,
    startSummaryPolling,
    stopSummaryPolling,
    fetchMeetings,
  ]);

  return (
    <SidebarContext.Provider value={contextValue}>
      {children}
    </SidebarContext.Provider>
  );
}
