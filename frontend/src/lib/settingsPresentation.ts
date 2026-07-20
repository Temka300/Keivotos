let prepared = false;
let pausedVideos: HTMLVideoElement[] = [];

export function prepareSettingsPresentation() {
  if (typeof document === 'undefined' || prepared) return;
  prepared = true;
  document.documentElement.dataset.settingsOpen = 'true';
  pausedVideos = Array.from(document.querySelectorAll<HTMLVideoElement>('#app video')).filter(
    (video) => !video.paused && !video.closest('.settings-layer'),
  );
  pausedVideos.forEach((video) => video.pause());
}

export function restoreSettingsPresentation(resumeVideos: boolean) {
  if (typeof document === 'undefined' || !prepared) return;
  delete document.documentElement.dataset.settingsOpen;
  if (resumeVideos) {
    pausedVideos.forEach((video) => {
      if (video.isConnected && !video.ended) void video.play().catch(() => {});
    });
  }
  pausedVideos = [];
  prepared = false;
}
