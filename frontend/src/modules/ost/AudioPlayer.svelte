<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import {filesApi} from '../../lib/filesApi';
  import {loopModeFor,autoNextFor,volumeFor,type LoopMode} from '../../lib/playbackPreferences';
  import VolumeControl from '../../components/VolumeControl.svelte';
  import SettingsSwitch from '../../components/SettingsSwitch.svelte';
  import {ostApi,type OstItem} from './api';
  export let track:OstItem;
  export let folderLabel:string;
  export let expanded=false;
  export let hasPrevious=false,hasNext=false,canWrap=false,navigating=false;
  export let navigationNotice='';
  export let onNavigate:(direction:-1|1,wrap:boolean)=>Promise<boolean>;
  export let onExpand:(event:MouseEvent)=>void;
  export let onBrowse:()=>void;
  let audio:HTMLAudioElement,view:HTMLDivElement;
  let mounted=false,alive=true,serial=0,endBusy=false;
  let playing=false,position=0,duration=0,failure='',notice='',artMissing=false;
  let loopMode:LoopMode='off',autoNext=true,volume=100;
  let stopLoop=()=>{},stopAuto=()=>{},stopVolume=()=>{};
  const loopOrder:LoopMode[]=['off','all','one'];
  $: if(mounted)void open(track);
  $: if(expanded&&mounted)void focusView();
  async function focusView(){await tick();if(alive&&expanded)view?.focus({preventScroll:true});}
  function stamp(seconds:number){
    const whole=Math.max(0,Math.floor(Number.isFinite(seconds)?seconds:0));
    return `${Math.floor(whole/60)}:${String(whole%60).padStart(2,'0')}`;
  }
  function current(event:Event){return alive&&event.currentTarget===audio;}
  function mediaError(event:Event){
    if(!current(event)||!audio.error||audio.error.code===1)return;
    failure='This track is unavailable or its audio format cannot play here. Choose another track or Retry.';
    notice='';playing=false;
  }
  async function play(item=track,generation=serial){
    const element=audio;
    try{await element.play();if(alive&&track===item&&generation===serial)notice='';}
    catch(caught){
      if(!alive||track!==item||generation!==serial||element!==audio)return;
      if(caught instanceof DOMException&&caught.name==='AbortError')return;
      if(caught instanceof DOMException&&caught.name==='NotAllowedError'){
        notice='Press Play to start audio.';return;
      }
      failure||='Could not play this track. Choose another track or Retry.';
    }
  }
  async function open(item:OstItem){
    const generation=++serial;
    audio?.pause();playing=false;position=0;duration=0;failure='';notice='';artMissing=false;endBusy=false;
    await tick();
    if(!alive||track!==item||generation!==serial)return;
    audio.volume=volume/100;
    void play(item,generation);
  }
  async function retry(){
    ++serial;failure='';notice='';position=0;duration=0;
    audio.load();await play();
  }
  function togglePlay(){if(!audio||failure)return;if(audio.paused)void play();else audio.pause();}
  async function navigate(direction:-1|1){await onNavigate(direction,loopMode==='all');}
  async function ended(event:Event){
    if(!current(event)||failure||endBusy)return;
    playing=false;
    const item=track,generation=serial;
    if(loopMode==='one'){audio.currentTime=0;void play(item,generation);return;}
    if(!autoNext)return;
    endBusy=true;
    try{
      const moved=await onNavigate(1,loopMode==='all');
      if(alive&&track===item&&serial===generation&&!moved&&loopMode==='all'&&!navigationNotice){
        audio.currentTime=0;void play(item,generation);
      }
    }finally{if(serial===generation)endBusy=false;}
  }
  function seek(event:Event){if(duration&&!failure)audio.currentTime=Number((event.currentTarget as HTMLInputElement).value);}
  function volumeChanged(event:Event){if(current(event)&&Math.round(audio.volume*100)!==volume)volumeFor('ost').set(Math.round(audio.volume*100));}
  function keys(event:KeyboardEvent){
    if(expanded&&event.key==='Escape'){event.preventDefault();onBrowse();return;}
    const target=event.target instanceof HTMLElement?event.target:null;
    if(!audio||failure||event.isComposing||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||target?.closest('button,input,textarea,select,a,[contenteditable="true"]'))return;
    if(event.key===' '||event.key==='Spacebar'){event.preventDefault();if(!event.repeat)togglePlay();}
    if((event.key==='ArrowLeft'||event.key==='ArrowRight')&&duration){
      event.preventDefault();audio.currentTime=Math.max(0,Math.min(duration,audio.currentTime+(event.key==='ArrowRight'?5:-5)));
      position=audio.currentTime;
    }
  }
  onMount(()=>{
    stopLoop=loopModeFor('ost').subscribe(value=>loopMode=value);
    stopAuto=autoNextFor('ost').subscribe(value=>autoNext=value);
    stopVolume=volumeFor('ost').subscribe(value=>{volume=value;if(audio&&audio.volume!==value/100)audio.volume=value/100;});
    mounted=true;
  });
  onDestroy(()=>{
    alive=false;++serial;stopLoop();stopAuto();stopVolume();
    if(audio){audio.pause();audio.removeAttribute('src');audio.load();}
  });
</script>

<div class="audio-player" class:expanded>
  {#key `${track.source_id}:${track.path}`}
    <!-- svelte-ignore a11y_media_has_caption -->
    <audio bind:this={audio} src={filesApi.fileUrl(track.source_id,track.path)} preload="metadata"
      on:error={mediaError} on:ended={ended}
      on:play={event=>{if(current(event))playing=true;}}
      on:pause={event=>{if(current(event))playing=false;}}
      on:timeupdate={event=>{if(current(event))position=audio.currentTime;}}
      on:durationchange={event=>{if(current(event))duration=Number.isFinite(audio.duration)?audio.duration:0;}}
      on:volumechange={volumeChanged}></audio>
  {/key}
  {#if expanded}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
    <div class="cover-view" role="region" aria-label="OST player" tabindex="-1" bind:this={view} on:keydown={keys}>
      <button class="back" aria-label="Back to tracks" on:click={onBrowse}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg></button>
      <div class="album-art"><span aria-hidden="true">♫</span>{#if !artMissing}<img alt="" src={ostApi.coverUrl(track.source_id,track.path,track.cover_version,600)} on:error={()=>artMissing=true}/>{/if}</div>
      <h2 title={track.name}>{track.name}</h2><p class="folder" title={folderLabel}>{folderLabel}</p>
    </div>
  {/if}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
  <section class="transport" aria-label="OST playback controls" tabindex="-1" on:keydown={keys}>
    {#if failure}<p role="alert">{failure} <button class="retry" on:click={retry}>Retry track</button></p>{/if}
    {#if notice||navigationNotice}<p role="status">{notice||navigationNotice}</p>{/if}
    <div class="track-line">
      <button class="now-playing" aria-label={`Open player for ${track.name}`} title={track.name} on:click={onExpand}>
        <span class="small-art"><span aria-hidden="true">♫</span>{#if !artMissing}<img alt="" src={ostApi.coverUrl(track.source_id,track.path,track.cover_version)} on:error={()=>artMissing=true}/>{/if}</span>
        <span class="track-name">{track.name}</span>
      </button>
    </div>
    <div class="control-row">
      <div class="auto-next" title="Auto next: advance when the current song ends"><SettingsSwitch label="Auto next" checked={autoNext} on:click={()=>autoNextFor('ost').set(!autoNext)}/></div>
      <div class="center">
        <div class="triplet">
          <button aria-label="Previous song" disabled={navigating||!(hasPrevious||loopMode==='all'&&canWrap)} on:click={()=>navigate(-1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14M19 5 8 12l11 7Z"/></svg></button>
          <button aria-label={playing?'Pause':'Play'} disabled={!!failure} on:click={togglePlay}><svg viewBox="0 0 24 24" aria-hidden="true">{#if playing}<path d="M8 5v14M16 5v14"/>{:else}<path d="m7 4 14 8-14 8Z"/>{/if}</svg></button>
          <button aria-label="Next song" disabled={navigating||!(hasNext||loopMode==='all'&&canWrap)} on:click={()=>navigate(1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5v14M5 5l11 7-11 7Z"/></svg></button>
        </div>
        <button class="loop-button" class:off={loopMode==='off'} aria-label={`Loop ${loopMode}`} title={`Loop ${loopMode}`} aria-pressed={loopMode!=='off'} on:click={()=>loopModeFor('ost').set(loopOrder[(loopOrder.indexOf(loopMode)+1)%loopOrder.length])}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 2l3 3-3 3M3 11V9a4 4 0 0 1 4-4h13M7 22l-3-3 3-3M21 13v2a4 4 0 0 1-4 4H4"/></svg>{#if loopMode==='one'}<span class="loop-one-mark">1</span>{/if}</button>
      </div>
      <div class="volume"><VolumeControl value={volume} disabled={!!failure} onChange={value=>volumeFor('ost').set(value)}/></div>
    </div>
    <div class="seek-row">
      <span class="time" aria-label="Current time">{stamp(position)}</span>
      <input class="seek" aria-label="Seek" aria-valuetext={`${stamp(position)} of ${stamp(duration)}`} type="range" min="0" max={duration||0} step="0.1" value={position} disabled={!duration||!!failure} style={`--progress:${duration?position/duration*100:0}%`} on:input={seek}/>
      <span class="time" aria-label="Track duration">{stamp(duration)}</span>
    </div>
  </section>
</div>

<style>
  .audio-player{display:flex;flex:none;min-height:0;min-width:0;flex-direction:column}.audio-player.expanded{flex:1}
  audio{display:none}.cover-view{position:relative;display:flex;flex:1;min-height:0;flex-direction:column;align-items:center;justify-content:center;overflow:auto;padding:56px 24px 24px;gap:16px}
  .cover-view:focus,.transport:focus{outline:none}.album-art{position:relative;display:grid;place-items:center;width:min(360px,60vw,40vh);aspect-ratio:1;flex:none;background:#20202d;border-radius:18px;color:#858599;font-size:80px;overflow:hidden}
  .album-art img,.small-art img{position:absolute;width:100%;height:100%;object-fit:cover}
  h2{max-width:800px;text-align:center;font-size:20px;line-height:1.45;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;overflow-wrap:anywhere}.folder{max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:#858599;font-size:12px}
  .back{position:absolute;display:grid;place-items:center;top:12px;left:24px;width:40px;height:40px;border:0;background:transparent;color:#eee;border-radius:999px;transition:width .18s ease,background-color .18s ease}.back:hover,.back:focus-visible{width:56px;background:#33333b}
  .transport{flex:none;border-top:1px solid #292936;background:#111117;padding:12px 24px 12px}.transport p{font-size:12px;margin:0 0 8px;color:#b6b6c6}.retry{text-decoration:underline}
  .track-line{display:flex;align-items:center;gap:12px;min-width:0}.now-playing{display:flex;align-items:center;gap:10px;min-width:0;flex:1;text-align:left}.small-art{position:relative;display:grid;place-items:center;width:36px;height:36px;flex:none;border-radius:8px;overflow:hidden;background:#20202d;color:#858599;font-size:20px}
  .track-name{min-width:0;font-size:13px;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;overflow-wrap:anywhere}.time{flex:none;color:#a5a5b5;font-size:11px;font-variant-numeric:tabular-nums}
  .control-row{position:relative;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;min-height:56px}.center{position:relative}.triplet{display:flex;align-items:center;gap:8px}.volume{justify-self:end}.auto-next{justify-self:start}
  .control-row button{display:grid;place-items:center;width:40px;height:40px;border:0;background:transparent;color:#eee;border-radius:50%;transition:background-color .15s ease}.control-row button:hover:not(:disabled){background:#ffffff20}button:disabled{opacity:.45;cursor:default}svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
  .control-row .loop-button{position:absolute;left:calc(100% + 8px);top:0}.loop-button.off{color:#8a8a92}.loop-one-mark{position:absolute;top:7px;left:8px;font-size:10px;font-weight:800;text-shadow:0 0 2px #111}
  .auto-next :global(.settings-switch){width:38px;height:22px}.auto-next :global(.settings-switch span){width:16px;height:16px}.auto-next :global(.settings-switch.checked span){transform:translateX(16px)}
  .seek-row{display:flex;align-items:center;gap:12px;min-width:0}.seek{display:block;flex:1;min-width:0;appearance:none;width:100%;height:20px;margin:0;padding:0;background:transparent;cursor:pointer}.seek::-webkit-slider-runnable-track{height:3px;background:linear-gradient(to right,var(--accent) var(--progress),#ffffff55 var(--progress))}.seek::-moz-range-track{height:3px;background:linear-gradient(to right,var(--accent) var(--progress),#ffffff55 var(--progress))}.seek::-webkit-slider-thumb{appearance:none;width:11px;height:11px;margin-top:-4px;border-radius:50%;background:var(--accent)}.seek::-moz-range-thumb{width:11px;height:11px;border:0;border-radius:50%;background:var(--accent)}
  button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
  @media(max-width:720px){.transport{padding-inline:12px}.control-row{grid-template-rows:40px 40px;grid-template-columns:1fr 1fr;gap:4px}.center{grid-row:1;grid-column:1/3;justify-self:center}.auto-next{grid-row:2;grid-column:1}.volume{grid-row:2;grid-column:2}.triplet{gap:8px}.album-art{width:min(320px,70vw,40vh)}.back{left:12px}}
  :global(html[data-motion='reduced']) .back,:global(html[data-motion='reduced']) .control-row button{transition:none}
  @media(prefers-reduced-motion:reduce){.back,.control-row button{transition:none}}
</style>
