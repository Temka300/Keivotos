import {get} from '../../lib/http';

export interface OstSource{source_id:string;name:string;available:boolean;}
export interface OstItem{source_id:string;path:string;name:string;ext:string;is_dir:boolean;size:number|null;mtime:number;available:boolean;}
export interface OstDirectory{source_id:string;parent:string;items:OstItem[];total:number;}
export const ostApi={
  folders:(signal?:AbortSignal)=>get<OstSource[]>('/ost/folders',undefined,signal),
  library:(sourceId:string,parent='',offset=0,signal?:AbortSignal)=>get<OstDirectory>('/ost/library',{source_id:sourceId,parent,offset,limit:120},signal),
};
