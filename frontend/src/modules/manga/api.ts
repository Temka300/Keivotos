import {get} from '../../lib/http';
export interface Chapter {path:string; kind:'folder'|'archive'; name:string;}
export interface Manga {source_id:string; path:string; name:string; cover:Chapter; cover_revision?:string|null;}
export interface PageMetadata {count:number; revision:string; revisions:string[];}

/** Keep a small image window alive so native image requests can reuse it. */
export function createPagePrefetch(){
  type Entry={image:HTMLImageElement;bytes:number;ready:boolean};
  const retained=new Map<string,Entry>(),attempted=new Set<string>();
  const budget=32*1024*1024;
  let adjacent:string[]=[],visibleReady=false,active:string|null=null,bytes=0;
  function release(url:string){
    const entry=retained.get(url);if(!entry)return;
    retained.delete(url);bytes-=entry.bytes;
    entry.image.onload=null;entry.image.onerror=null;entry.image.removeAttribute('src');
    if(active===url)active=null;
  }
  function pump(){
    if(!visibleReady||active)return;
    const url=adjacent.find(candidate=>!attempted.has(candidate));if(!url)return;
    attempted.add(url);active=url;
    const image=new Image(),entry:Entry={image,bytes:0,ready:false};retained.set(url,entry);
    image.fetchPriority='low';image.decoding='async';
    const finish=(ready:boolean)=>{
      // A late load/decode after cancellation cannot start work for an old window.
      if(retained.get(url)!==entry)return;
      if(ready)entry.ready=true;else release(url);
      active=null;pump();
    };
    image.onerror=()=>finish(false);
    image.onload=()=>{
      const size=image.naturalWidth*image.naturalHeight*4;
      if(!size||bytes+size>budget){finish(false);return;}
      entry.bytes=size;bytes+=size;
      void image.decode().then(()=>finish(true),()=>finish(false));
    };
    image.src=url;
  }
  return {
    update(current:string,neighbors:string[],ready:boolean){
      adjacent=[...new Set(neighbors)].filter(candidate=>candidate!==current).slice(0,3);
      visibleReady=ready;
      const wanted=new Set([current,...adjacent]);
      for(const old of retained.keys())if(!wanted.has(old)||(!ready&&old!==current&&!retained.get(old)!.ready)){
        release(old);attempted.delete(old);
      }
      for(const old of attempted)if(!wanted.has(old))attempted.delete(old);
      if(ready)attempted.add(current);
      pump();
    },
    clear(){
      adjacent=[];visibleReady=false;
      for(const url of retained.keys())release(url);
      attempted.clear();
    },
  };
}
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
