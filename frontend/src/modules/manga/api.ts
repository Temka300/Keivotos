import {get} from '../../lib/http';
export interface Chapter {path:string; kind:'folder'|'archive'; name:string;}
export interface Manga {source_id:string; path:string; name:string; cover:Chapter; cover_revision?:string|null;}
export interface PageMetadata {count:number; revision:string; revisions:string[];}
export const mangaApi = {
  library:(q:string,offset=0,signal?:AbortSignal)=>get<{items:Manga[];total:number}>('/manga/library',{q,offset},signal),
  chapters:(manga:Manga,signal?:AbortSignal)=>get<{items:Chapter[]}>('/manga/chapters',{source_id:manga.source_id,path:manga.path},signal),
  pages:(manga:Manga,chapter:Chapter,signal?:AbortSignal)=>get<PageMetadata>('/manga/pages',{source_id:manga.source_id,path:chapter.path,kind:chapter.kind,metadata:true},signal),
  page:(manga:Manga,chapter:Chapter,page=0,cover=false,revision?:string,representation:'original'|'webp'='original')=>{
    const parameters=new URLSearchParams({source_id:manga.source_id,path:chapter.path,kind:chapter.kind,page:String(page),cover:String(cover),representation:cover?'webp':representation});
    const version=cover?manga.cover_revision:revision;
    if(version)parameters.set('revision',version);
    return '/api/manga/page?'+parameters;
  },
};
