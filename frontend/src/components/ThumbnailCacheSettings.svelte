<script lang="ts">
 import {onMount} from 'svelte';
 import {slide} from 'svelte/transition';
 import {suiteDataApi as api,type StorageUsage} from '../lib/suiteDataApi';
 let usage:StorageUsage|null=null,expanded=false,busy=false,error='',message='',limitGb=10;
 const mb=(bytes:number)=>`${(bytes/1024**2).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} MB`;
 async function load(){usage=await api.getStorageUsage();limitGb=Math.round(usage.thumbnails.limit_bytes/1024**3);}
 async function run(action:'cleanup'|'clear'){
  if(busy||!usage)return;
  if(action==='clear'&&!confirm(`Clear ${usage.thumbnails.files} generated thumbnails? Original media and saved data will stay untouched.`))return;
  busy=true;error='';message='';
  try{const result=await(action==='clear'?api.clearThumbnailCache():api.cleanupThumbnailCache());message=`Removed ${result.removed} thumbnail files.`;await load();}
  catch(e){error=e instanceof Error?e.message:String(e);}finally{busy=false;}
 }
 async function limit(){busy=true;error='';try{await api.setThumbnailCacheLimit(limitGb);await load();}catch(e){error=String(e);}finally{busy=false;}}
 async function startup(event:Event){busy=true;error='';try{await api.setCacheStartup((event.currentTarget as HTMLInputElement).checked);await load();}catch(e){error=String(e);}finally{busy=false;}}
 onMount(()=>{void load().catch(e=>error=String(e));});
</script>
<section id="setting-thumbnail-cache" class="data-storage" aria-label="Data & storage">
 {#if usage}
 <div class="row total" title={usage.data_location}><span>Keivotos data total</span><span class="size">{mb(usage.total_bytes)}</span></div>
 <div class="row"><span>Thumbnail</span><div class="actions"><button disabled={busy} on:click={()=>run('cleanup')}>Remove stale</button><button disabled={busy} on:click={()=>run('clear')}>Clear all</button><button aria-expanded={expanded} aria-controls="thumbnail-details" on:click={()=>expanded=!expanded}>{expanded?'Show less':'Show all'}</button></div><span class="size">{mb(usage.categories.thumbnails)}</span></div>
 {#if expanded}
 <div id="thumbnail-details" class="details" transition:slide={{duration:window.matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.dataset.motion==='reduced'?0:180}}>
  <div class="row"><span>Thumbnail</span><span class="size">{mb(usage.categories.thumbnails)}</span></div>
  {#each ['300','600','1200'] as tier}<div class="row tier"><span>{tier} px</span><span class="size">{mb(usage.thumbnails.tier_bytes[tier]||0)}</span></div>{/each}
  <div class="row"><label for="thumbnail-limit">Maximum</label><select id="thumbnail-limit" bind:value={limitGb} disabled={busy} on:change={limit}>{#each Array.from(new Set([1,2,5,10,20,50,100,limitGb])).sort((a,b)=>a-b) as value}<option value={value}>{value} GB</option>{/each}</select></div>
  <div class="row"><label for="stale-on-startup">Remove stale on startup</label><input id="stale-on-startup" type="checkbox" role="switch" checked={usage.cleanup_on_startup} disabled={busy} on:change={startup}/></div>
 </div>
 {/if}
 <div class="row"><span>Cache</span><span class="size">{mb(usage.categories.cache)}</span></div>
 {#each usage.modules as module}<div class="row"><span>{module.name} Module</span><span class="size">{mb(usage.categories[module.id]||0)}</span></div>{/each}
 {#each [['backups','Backups'],['databases','Databases'],['logs','Logs & Diagnostics']] as [id,label]}<div class="row"><span>{label}</span><span class="size">{mb(usage.categories[id]||0)}</span></div>{/each}
 {:else if !error}<div class="row">Loading…</div>{/if}
</section>
{#if usage?.unreadable}<p role="status">Some locations could not be read. Sizes are partial.</p>{/if}
{#if message}<p role="status">{message}</p>{/if}
{#if error}<p role="alert">{error} <button on:click={()=>load().then(()=>error='').catch(e=>error=String(e))}>Retry</button></p>{/if}
<style>
 .data-storage{border:1px solid #2d2f3f;border-radius:12px;background:#0f1018;overflow:hidden;color:#ececf3;font-size:14px}.row{min-height:54px;padding:10px 17px;display:flex;align-items:center;gap:16px}.row+.row,.details{border-top:1px solid #232532}.row>span:first-child,.row>label{flex:1}.size{font-variant-numeric:tabular-nums;color:#a2a4b6;white-space:nowrap}.total{font-weight:500}.total .size{color:#ececf3}.actions{display:flex;gap:8px}button,select{border:1px solid #343749;border-radius:8px;background:#0d0e15;color:#ececf3;min-height:32px;padding:5px 10px;font-size:12px;white-space:nowrap}button:hover{border-color:var(--accent)}button:disabled{opacity:.4}.details{background:#0c0d14;border-bottom:1px solid #232532}.details .row{min-height:44px}.tier{padding-left:32px}input{accent-color:var(--accent);width:16px;height:16px}p{font-size:12px;color:#a2a4b6;padding:8px 0}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:700px){.row{flex-wrap:wrap}.actions{width:100%;justify-content:flex-end;order:2}}
</style>
