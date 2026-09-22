import type {PlaybackFailure} from '../../lib/playback';
import {get,post} from '../../lib/http';
export interface Download {id:string;url:string;source_id:string;title:string;status:string;progress:number;path:string;thumbnail:string;error:string;}
export interface EngineStatus {ready:boolean;missing:string[];folders:{id:string;name:string}[];}
export interface SaveLocation {mode:'default'|'custom';path:string;source_id:string;default_path:string;}
export const youtubeApi={
 playbackError:(id:string,reason:PlaybackFailure)=>post('/youtube/playback-error',{id,reason}),
 settings:()=>get<SaveLocation>('/youtube/settings'),
 saveSettings:(mode:'default'|'custom',path?:string)=>post<SaveLocation>('/youtube/settings',{mode,path}),
 status:()=>get<EngineStatus>('/youtube/status'),
 library:(q:string,offset=0,signal?:AbortSignal)=>get<{items:Download[];total:number}>('/youtube/library',{q,offset},signal),
 download:(url:string,video:string,audio:string)=>post<Download>('/youtube/downloads',{url,video,audio}),
 cancel:(id:string)=>post<Download>(`/youtube/downloads/${id}/cancel`),
 retry:(id:string)=>post<Download>(`/youtube/downloads/${id}/retry`),
};
