import {get} from '../../lib/http';
export interface Chapter {path:string; kind:'folder'|'archive'; name:string;}
export interface Manga {source_id:string; path:string; name:string; cover:Chapter;}
export const mangaApi = {
  library:(q:string,offset=0,signal?:AbortSignal)=>get<{items:Manga[];total:number}>('/manga/library',{q,offset},signal),
  chapters:(manga:Manga,signal?:AbortSignal)=>get<{items:Chapter[]}>('/manga/chapters',{source_id:manga.source_id,path:manga.path},signal),
  pages:(manga:Manga,chapter:Chapter,signal?:AbortSignal)=>get<{count:number}>('/manga/pages',{source_id:manga.source_id,path:chapter.path,kind:chapter.kind},signal),
  page:(manga:Manga,chapter:Chapter,page=0,cover=false)=>'/api/manga/page?'+new URLSearchParams({source_id:manga.source_id,path:chapter.path,kind:chapter.kind,page:String(page),cover:String(cover)}),
};
