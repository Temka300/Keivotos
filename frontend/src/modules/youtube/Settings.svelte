<script lang="ts">
 import {getContext,onMount} from 'svelte';
 import {SETTINGS_SESSION,type SettingsSession} from '../../lib/settingsSession';
 import {youtubeApi,type SaveLocation} from './api';
 export let selectedSection:string;
 export let query='';
 const session=getContext<SettingsSession>(SETTINGS_SESSION);
 let location:SaveLocation|null=null,busy=false,error='';
 onMount(async()=>{try{location=await youtubeApi.settings();}catch(e){error=String(e);}});
 async function save(mode:'default'|'custom',path?:string){
  busy=true;error='';
  try{location=await youtubeApi.saveSettings(mode,path);}
  catch(e){error=e instanceof Error?e.message:String(e);}finally{busy=false;}
 }
 async function browse(){
  if(busy||location?.mode!=='custom')return;
  busy=true;error='';
  try{const path=await session.pickDirectory(location.path||location.default_path);if(path)await save('custom',path);}
  catch(e){error=String(e);}finally{busy=false;}
 }
</script>
{#if !query&&selectedSection==='youtube-downloads'}
 <section id="setting-youtube-location" class="location-settings">
  {#if location}
  <div class="row"><span>Save to location</span><div class="segments"><button class:active={location.mode==='default'} aria-pressed={location.mode==='default'} disabled={busy} on:click={()=>save('default')}>Default</button><button class:active={location.mode==='custom'} aria-pressed={location.mode==='custom'} disabled={busy} on:click={()=>save('custom')}>Custom</button></div></div>
  <div class="row"><label for="youtube-save-path">Save to path</label><div class="location-controls"><input id="youtube-save-path" readonly value={location.path} disabled={location.mode==='default'||busy} title={location.path}/><button class="change" disabled={location.mode==='default'||busy} on:click={browse}>Change folder</button></div></div>
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
 </section>
{/if}
<style>
 .location-settings{max-width:816px;margin:auto;border:1px solid #2d2f3f;border-radius:12px;background:#0f1018;overflow:hidden;color:#ececf3;font-size:14px}
 .row{min-height:56px;padding:10px 17px;display:flex;align-items:center;justify-content:space-between;gap:16px}.row+.row{border-top:1px solid #232532}.row>span,.row>label{flex-shrink:0}
 .segments{display:flex;border:1px solid #343749;border-radius:8px;overflow:hidden;background:#0d0e15}.segments button{width:98px;min-height:32px;font-size:12px;color:#8e91a3}.segments button+button{border-left:1px solid #2d3040}.segments button.active{background:color-mix(in srgb,var(--accent) 20%,#0d0e15);color:#ececf3;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--accent) 40%,transparent)}
 .location-controls{display:flex;align-items:center;gap:12px;min-width:0;flex:0 1 512px}.change{border:1px solid #343749;border-radius:8px;background:#0d0e15;color:#ececf3;min-height:34px;padding:6px 14px;font-size:13px;white-space:nowrap;flex-shrink:0;min-width:110px}
 input{min-width:0;flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;padding:8px 13px;font-size:12px;color:#a2a4b6;background:#0d0e15;border:1px solid #343749;border-radius:8px}button:disabled,input:disabled{opacity:.4}p{padding:10px 17px;color:#fca5a5;font-size:13px}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 @media(max-width:650px){.row:last-of-type{align-items:flex-start;flex-direction:column}.location-controls{flex:auto;width:100%}}
</style>
