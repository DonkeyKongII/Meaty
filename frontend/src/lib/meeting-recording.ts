import { recordingService } from '@/services/recordingService';
let owned = false;
export const companionOwnsRecording = () => owned;
export const clearCompanionRecording = () => { owned = false; };
export function consumeCompanionStart() {
  const requested = sessionStorage.getItem('meetilyCompanionStart') === 'true';
  sessionStorage.removeItem('meetilyCompanionStart');
  return requested;
}
export async function startWithOwnership(companion: boolean, ...args: Parameters<typeof recordingService.startRecordingWithDevices>) {
  await recordingService.startRecordingWithDevices(...args);
  owned = companion;
}
