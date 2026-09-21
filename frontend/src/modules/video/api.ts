import {get, post} from '../../lib/http';
export interface VideoItem { source_id:string; path:string; name:string; ext:string; size:number; mtime:number; }
export type PlaybackFailure = 'unsupported_format' | 'network' | 'decode' | 'unsupported_codec' | 'playback' | 'fullscreen';
export const videoApi = {
  library:(q:string, offset=0, signal?:AbortSignal)=>get<{items:VideoItem[];total:number}>('/video/library',{q,offset,limit:120},signal),
  error:(item:VideoItem, reason:PlaybackFailure)=>post('/video/playback-error',{source_id:item.source_id,path:item.path,reason}),
};
