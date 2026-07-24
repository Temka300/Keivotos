// Pure preview-mode resolution for the Files info panel (V1.1.1).
//
// The inline sets MUST mirror the backend allowlist in
// backend/files_base/serving.py: the base only renders inline what the server
// is willing to serve inline. html/svg/js and unknown types deliberately have
// no preview (they download instead), and MIDI/office/3D/zip show a type icon.

export type PreviewMode = 'image' | 'video' | 'audio' | 'pdf' | 'text' | 'none';

const IMAGE = new Set(['png', 'jpg', 'jpeg', 'jfif', 'gif', 'webp', 'avif', 'bmp']);
const VIDEO = new Set(['mp4', 'webm', 'm4v']);
const AUDIO = new Set(['mp3', 'flac', 'wav', 'ogg', 'oga', 'm4a']);
const TEXT = new Set(['srt', 'txt', 'ass', 'ssa', 'vtt', 'md', 'log', 'lrc']);

/** The subject an info panel is describing: a browsed file or the current folder. */
export interface Subject {
  sourceId: string;
  path: string; // relative to the source root; '' is the source root itself
  name: string;
  isDir: boolean;
  ext: string | null;
  size: number | null;
  mtime: number | null;
  absolutePath: string;
}

export function previewMode(ext: string | null | undefined): PreviewMode {
  const e = (ext ?? '').toLowerCase();
  if (IMAGE.has(e)) return 'image';
  if (VIDEO.has(e)) return 'video';
  if (AUDIO.has(e)) return 'audio';
  if (e === 'pdf') return 'pdf';
  if (TEXT.has(e)) return 'text';
  return 'none';
}

/** Emoji glyph for a tile or an unpreviewable subject. */
export function fileGlyph(entry: { is_dir: boolean; ext?: string | null }): string {
  if (entry.is_dir) return '📁';
  const ext = (entry.ext ?? '').toLowerCase();
  if (IMAGE.has(ext)) return '🖼️';
  if (VIDEO.has(ext) || ext === 'mkv' || ext === 'mov' || ext === 'avi') return '🎞️';
  if (AUDIO.has(ext) || ext === 'mid' || ext === 'midi') return '🎵';
  if (ext === 'pdf' || TEXT.has(ext) || ext === 'doc' || ext === 'docx' || ext === 'xlsx' || ext === 'csv' || ext === 'epub') return '📄';
  return '📦';
}

/** Human label for a link kind, for the origin section. */
export function linkKindLabel(kind: string): string {
  switch (kind) {
    case 'source': return 'Source';
    case 'discussion': return 'Discussion';
    case 'mirror': return 'Mirror';
    case 'author': return 'Author';
    default: return 'Link';
  }
}
