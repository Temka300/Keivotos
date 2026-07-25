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

/** Extensions the backend can actually produce a thumbnail for.
 *
 * Mirrors ``SUPPORTED_IMAGES | SUPPORTED_VIDEOS`` in backend/thumbnails.py, which
 * is deliberately narrower than the inline-preview sets above: avif, bmp and m4v
 * render inline but have no thumbnail path. Asking outside this set only earns a
 * 404, so the grid checks first rather than firing one doomed request per tile.
 */
const THUMBNAILABLE = new Set(['png', 'jpg', 'jpeg', 'jfif', 'gif', 'webp', 'mp4', 'webm']);

/** Whether a browsed entry should try for a real thumbnail instead of a glyph.
 *
 * Folders always try. Only the backend index knows whether a folder holds a
 * cover image anywhere in its subtree, so the tile asks and falls back to the
 * folder glyph on a 404 — bounded by how many folder tiles are on screen, since
 * the images are lazy.
 */
export function hasThumbnail(entry: { is_dir: boolean; ext?: string | null }): boolean {
  if (entry.is_dir) return true;
  return THUMBNAILABLE.has((entry.ext ?? '').toLowerCase());
}

/** Container types whose table of contents the base can list without extracting.
 *
 * The server judges by content (`zipfile.is_zipfile`), so this set only decides
 * where the UI offers the control; a mislabelled file still gets a clean 415.
 */
const LISTABLE_ARCHIVES = new Set(['zip', 'cbz', 'epub']);

export function isListableArchive(ext: string | null | undefined): boolean {
  return LISTABLE_ARCHIVES.has((ext ?? '').toLowerCase());
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
