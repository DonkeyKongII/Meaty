import { useState, useEffect } from 'react';
import { recordingService } from '@/services/recordingService';

interface UseRecordingStateSyncReturn {
  isBackendRecording: boolean;
  isRecordingDisabled: boolean;
  setIsRecordingDisabled: (value: boolean) => void;
}

/**
 * Custom hook for synchronizing frontend recording state with backend.
 * Polls backend every 1 second to detect recording state changes.
 *
 * Features:
 * - Backend state synchronization (1-second polling)
 * - Recording disabled flag management (prevents re-recording during processing)
 */
export function useRecordingStateSync(
  isRecording: boolean,
  setIsRecording: (value: boolean) => void,
  setIsMeetingActive: (value: boolean) => void
): UseRecordingStateSyncReturn {
  const [isRecordingDisabled, setIsRecordingDisabled] = useState(false);

  useEffect(() => {
    console.log('Setting up recording state check effect, current isRecording:', isRecording);

    const checkRecordingState = async () => {
      try {
        console.log('checkRecordingState called');
        console.log('About to call is_recording command');
        const isCurrentlyRecording = await recordingService.isRecording();
        console.log('checkRecordingState: backend recording =', isCurrentlyRecording, 'UI recording =', isRecording);

        if (isCurrentlyRecording && !isRecording) {
          console.log('Recording is active in backend but not in UI, synchronizing state...');
          setIsRecording(true);
          setIsMeetingActive(true);
        } else if (!isCurrentlyRecording && isRecording) {
          console.log('Recording is inactive in backend but active in UI, synchronizing state...');
          setIsRecording(false);
        }
      } catch (error) {
        console.error('Failed to check recording state:', error);
      }
    };

    // Test if Tauri is available
    console.log('Testing Tauri availability...');
    if (typeof window !== 'undefined' && (window as any).__TAURI__) {
      console.log('Tauri is available, listening for recording events and visibility changes');
      checkRecordingState();

      let unlistenStarted: (() => void) | undefined;
      let unlistenStopped: (() => void) | undefined;

      const setupEventListeners = async () => {
        try {
          unlistenStarted = await recordingService.onRecordingStarted(() => {
            console.log('useRecordingStateSync: onRecordingStarted event received');
            setIsRecording(true);
            setIsMeetingActive(true);
          });
          unlistenStopped = await recordingService.onRecordingStopped(() => {
            console.log('useRecordingStateSync: onRecordingStopped event received');
            setIsRecording(false);
          });
        } catch (err) {
          console.error('Failed to attach recording event listeners:', err);
        }
      };

      setupEventListeners();

      // Immediate refresh on visibility restore
      const handleVisibilityChange = () => {
        if (document.visibilityState === 'visible') {
          checkRecordingState();
        }
      };

      document.addEventListener('visibilitychange', handleVisibilityChange);

      return () => {
        console.log('Cleaning up recording state event listeners');
        if (unlistenStarted) unlistenStarted();
        if (unlistenStopped) unlistenStopped();
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      };
    } else {
      console.log('Tauri is not available, skipping state check');
    }
  }, [isRecording, setIsRecording, setIsMeetingActive]);

  return {
    isBackendRecording: isRecording,
    isRecordingDisabled,
    setIsRecordingDisabled,
  };
}
