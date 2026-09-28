<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import type {PlaybackMedia,PlaybackFailure} from '../lib/playback';
  import {hideControlsSeconds,loopModeFor,autoNextFor,type LoopMode,type PlaybackOwner} from '../lib/playbackPreferences';
  import SettingsSwitch from './SettingsSwitch.svelte';
  export let media:PlaybackMedia;
  export let owner:PlaybackOwner;
  export let label='Video player';
  export let backLabel='Back to videos';
  export let hasPrevious=false;
  export let hasNext=false;
  export let canWrap=false;
  export let navigating=false;
  export let navigationNotice='';
  export let onClose:()=>void;
  export let onNavigate:(direction:-1|1,wrap:boolean)=>Promise<boolean>;
  export let onFailure:(item:PlaybackMedia,reason:PlaybackFailure)=>Promise<unknown>;
  let player:HTMLVideoElement;
  let viewer:HTMLDivElement;
  let playing=false,position=0,duration=0,failure='',notice='';
  let reported=new Set<PlaybackFailure>();
  let alive=true,mounted=false;
  let controlsVisible=true,pointerOverControls=false,keyboardActive=false;
  let idleSeconds=5;
  let idleTimer:ReturnType<typeof setTimeout>|undefined;
  let stopPreference:()=>void=()=>{};
  let stopLoop:()=>void=()=>{};
  let stopAutoNext:()=>void=()=>{};
  let loopMode:LoopMode='off';
  let autoNext=false,endBusy=false;
  const loopOrder:LoopMode[]=['off','all','one'];
  function cycleLoop(){loopModeFor(owner).set(loopOrder[(loopOrder.indexOf(loopMode)+1)%loopOrder.length]);reveal();}
  function toggleAutoNext(){autoNextFor(owner).set(!autoNext);reveal();}
  async function navigate(direction:-1|1){
    try{await onNavigate(direction,loopMode==='all');}
    catch{notice='Could not load another video. Try again.';controlsVisible=true;clearIdle();}
  }
  async function replay(){
    if(!player||failure)return;
    player.currentTime=0;
    try{await player.play();}
    catch{failure='Could not replay this video. See Logs.';controlsVisible=true;clearIdle();void report('playback');}
  }
  async function ended(){
    playing=false;controlsVisible=true;clearIdle();
    if(endBusy||failure)return;
    if(loopMode==='one'){void replay();return;}
    if(!autoNext)return;
    const item=media;
    endBusy=true;
    try{
      const moved=await onNavigate(1,loopMode==='all');
      if(alive&&media===item&&!moved&&loopMode==='all')await replay();
    }catch{if(alive&&media===item)notice='Could not load the next video. Try again.';}
    finally{endBusy=false;}
  }
  function clearIdle(){if(idleTimer!==undefined){clearTimeout(idleTimer);idleTimer=undefined;}}
  function scheduleIdle(){
    clearIdle();
    if(!playing||failure||notice||navigationNotice||pointerOverControls||keyboardActive)return;
    idleTimer=setTimeout(()=>{controlsVisible=false;idleTimer=undefined;if(viewer?.contains(document.activeElement))viewer.focus();},idleSeconds*1000);
  }
  function reveal(){controlsVisible=true;scheduleIdle();}
  function pointerMove(){keyboardActive=false;reveal();}
  function controlFocus(event:FocusEvent){if(event.target!==viewer&&keyboardActive){controlsVisible=true;clearIdle();}}
  function controlBlur(){void tick().then(()=>{if(alive&&(!viewer?.contains(document.activeElement)||document.activeElement===viewer)){keyboardActive=false;scheduleIdle();}});}
  $: if(navigationNotice){controlsVisible=true;clearIdle();}
  $: if(mounted) void open(media);
  async function report(reason: PlaybackFailure) {
    if (!media || reported.has(reason)) return;
    reported.add(reason);
    const item = media;
    try {await onFailure(item, reason);}
    catch { if (alive && media === item) failure += ' Could not write to Logs.'; }
  }
  function mediaError() {
    if (!media || !player?.error || player.error.code === 1) return;
    failure = 'This video cannot play here. See Logs.';
    clearIdle();controlsVisible=true;
    void report(player.error.code === 2 ? 'network' : player.error.code === 3 ? 'decode' : 'unsupported_codec');
  }
  async function open(item: PlaybackMedia) {
    player?.pause();
    playing = false; position = 0; duration = 0; failure = ''; notice = ''; reported = new Set();
    clearIdle();controlsVisible=true;keyboardActive=false;pointerOverControls=false;
    endBusy=false;
    await tick(); if (!alive || media !== item) return; viewer?.focus();
    if (!['mp4','m4v','webm'].includes(item.ext)) {
      failure = 'This format cannot play here. See Logs.'; void report('unsupported_format'); return;
    }
    try {await player.play();}
    catch (caught) {
      // A browser autoplay policy is not a broken file: Play remains available.
      if (caught instanceof DOMException && (caught.name === 'NotAllowedError' || caught.name === 'AbortError')) return;
      if (media !== item) return;
      failure = 'This video cannot play here. See Logs.'; void report('playback');
    }
  }
  async function togglePlay() {
    if (!player || failure) return;
    if (!player.paused) player.pause();
    else try {await player.play();} catch {failure = 'Could not play this video. See Logs.'; void report('playback');}
  }
  async function fullscreen() {
    try {if (document.fullscreenElement) await document.exitFullscreen(); else await viewer.requestFullscreen();}
    catch {notice = 'Fullscreen is unavailable. See Logs.';controlsVisible=true;clearIdle();void report('fullscreen');}
  }
  async function close() {
    player?.pause();
    if (document.fullscreenElement === viewer) await document.exitFullscreen().catch(() => {});
    onClose();
  }
  function playerKeys(event: KeyboardEvent) {
    if(event.key==='Tab'&&!controlsVisible){event.preventDefault();keyboardActive=true;controlsVisible=true;clearIdle();void tick().then(()=>{const controls=[...viewer.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)')];(event.shiftKey?controls.at(-1):controls[0])?.focus();});return;}
    if(event.key==='Tab'||event.key.startsWith('Arrow')){keyboardActive=true;controlsVisible=true;clearIdle();}
    if (event.key === 'Escape' && !document.fullscreenElement) {void close(); return;}
    if (event.key !== 'Tab') return;
    const controls = [...viewer.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)')];
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === viewer)) {event.preventDefault(); last?.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
  }
  function seek(event: Event) {
    if (player && Number.isFinite(duration)) player.currentTime = Number((event.currentTarget as HTMLInputElement).value);
  }
  onMount(()=>{stopPreference=hideControlsSeconds.subscribe(seconds=>{idleSeconds=seconds;scheduleIdle();});stopLoop=loopModeFor(owner).subscribe(value=>loopMode=value);stopAutoNext=autoNextFor(owner).subscribe(value=>autoNext=value);mounted=true;});
  onDestroy(()=>{alive=false;clearIdle();stopPreference();stopLoop();stopAutoNext();player?.pause();if(document.fullscreenElement===viewer)void document.exitFullscreen().catch(()=>{});});
</script>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
  <div class="video-viewer" bind:this={viewer} role="dialog" aria-modal="true" aria-label={label} tabindex="-1" on:keydown={playerKeys} on:pointerdown={() => keyboardActive=false} on:pointermove={pointerMove} on:touchstart={reveal} on:focusin={controlFocus} on:focusout={controlBlur}>
    {#key media.src}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={player} src={['mp4','m4v','webm'].includes(media.ext) ? media.src : undefined} playsinline preload="metadata" on:error={mediaError} on:play={() => {playing=true;scheduleIdle();}} on:pause={() => {playing=false;controlsVisible=true;clearIdle();}} on:ended={ended} on:timeupdate={() => position = player.currentTime} on:durationchange={() => duration = Number.isFinite(player.duration) ? player.duration : 0}></video>
    {/key}
    <button class="back" class:controls-hidden={!controlsVisible} aria-label={backLabel} tabindex={controlsVisible?0:-1} on:pointerenter={() => {pointerOverControls=true;clearIdle();}} on:pointerleave={() => {pointerOverControls=false;scheduleIdle();}} on:click={close}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7" /></svg></button>
    {#if failure || notice || navigationNotice}<p class="playback-error" role="alert">{failure || notice || navigationNotice}</p>{/if}
    <div class="player-controls" role="group" aria-label="Playback controls" class:controls-hidden={!controlsVisible} inert={!controlsVisible} on:pointerenter={() => {pointerOverControls=true;clearIdle();}} on:pointerleave={() => {pointerOverControls=false;scheduleIdle();}}>
      <input aria-label="Seek" type="range" min="0" max={duration || 0} step="0.1" value={position} style={`--progress:${duration ? position / duration * 100 : 0}%`} disabled={!duration || !!failure} on:input={seek} />
      <div class="control-row">
        <button aria-label="Previous video" disabled={navigating || !(hasPrevious||(loopMode==='all'&&canWrap))} on:click={() => navigate(-1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14M19 5 8 12l11 7Z" /></svg></button>
        <button aria-label={playing ? 'Pause' : 'Play'} disabled={!!failure} on:click={togglePlay}><svg viewBox="0 0 24 24" aria-hidden="true">{#if playing}<path d="M8 5v14M16 5v14" />{:else}<path d="m7 4 13 8-13 8Z" />{/if}</svg></button>
        <button aria-label="Next video" disabled={navigating || !(hasNext||(loopMode==='all'&&canWrap))} on:click={() => navigate(1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5v14M5 5l11 7-11 7Z" /></svg></button>
        <div class="auto-next"><SettingsSwitch label="Auto next" checked={autoNext} on:click={toggleAutoNext}/></div>
        <button class="loop-button" class:off={loopMode==='off'} class:all={loopMode==='all'} class:one={loopMode==='one'} aria-label={loopMode==='one'?'Loop one':loopMode==='all'?'Loop all':'Loop off'} title={loopMode==='one'?'Loop one':loopMode==='all'?'Loop all':'Loop off'} aria-pressed={loopMode!=='off'} on:click={cycleLoop}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 2l3 3-3 3"/><path d="M3 11V9a4 4 0 0 1 4-4h13"/><path d="M7 22l-3-3 3-3"/><path d="M21 13v2a4 4 0 0 1-4 4H4"/></svg>{#if loopMode==='one'}<span class="loop-one-mark">1</span>{/if}</button>
        <button class="fullscreen" aria-label="Fullscreen" on:click={fullscreen}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5" /></svg></button>
      </div>
    </div>
  </div>
<style>
 .video-viewer{position:fixed;inset:0;z-index:110;background:black;display:grid;place-items:center}
 video{width:100%;height:100%;max-height:100dvh;object-fit:contain}
 .back{position:absolute;top:16px;left:16px;width:40px;height:40px;display:grid;place-items:center;border:0;background:transparent;border-radius:999px;color:#eee;transition:width .18s ease,background-color .18s ease,opacity .18s ease}
 .back:hover,.back:focus-visible{width:56px;background:#33333b}
 .back.controls-hidden,.player-controls.controls-hidden{opacity:0;pointer-events:none}
 .player-controls{transition:opacity .18s ease}
 .video-viewer svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
 .player-controls{position:absolute;bottom:0;left:0;right:0;display:flex;flex-direction:column;gap:8px;background:linear-gradient(transparent,#000b);padding:32px 24px 16px}
 .control-row{display:flex;align-items:center;gap:12px}
 .player-controls button{display:grid;place-items:center;width:40px;height:40px;border:0;background:transparent;color:#eee;border-radius:50%;transition:background-color .15s ease}
 .player-controls button:hover:not(:disabled){background:#ffffff20}
 .auto-next{margin-left:auto;display:flex;align-items:center}
 .auto-next :global(.settings-switch){width:38px;height:22px}
 .auto-next :global(.settings-switch span){width:16px;height:16px}
 .auto-next :global(.settings-switch.checked span){transform:translateX(16px)}
 .loop-button{position:relative}
 .loop-button.off{color:#8a8a92}
 .loop-button.all,.loop-button.one{color:#fff}
 .loop-one-mark{position:absolute;top:7px;left:8px;font-size:10px;line-height:1;font-weight:800;color:#fff;pointer-events:none;z-index:2;text-shadow:-1px 0 0 #111,1px 0 0 #111,0 -1px 0 #111,0 1px 0 #111,-1px -1px 0 #111,1px -1px 0 #111,-1px 1px 0 #111,1px 1px 0 #111}
 .loop-one-mark::before{content:"";position:absolute;z-index:-1;left:-2px;right:-2px;top:5px;height:5px;border-radius:3px;background:#151515}
 .player-controls input{appearance:none;width:100%;height:20px;margin:0;padding:0;border:0;border-radius:0;background:transparent;cursor:pointer}
 .player-controls input::-webkit-slider-runnable-track{height:3px;border:0;background:linear-gradient(to right,var(--accent) var(--progress),#ffffff55 var(--progress))}
 .player-controls input::-moz-range-track{height:3px;border:0;background:linear-gradient(to right,var(--accent) var(--progress),#ffffff55 var(--progress))}
 .player-controls input::-webkit-slider-thumb{appearance:none;width:11px;height:11px;margin-top:-4px;border:0;border-radius:50%;background:var(--accent)}
 .player-controls input::-moz-range-thumb{width:11px;height:11px;border:0;border-radius:50%;background:var(--accent)}
 :global(html[data-motion='reduced']) .back,:global(html[data-motion='reduced']) .player-controls,:global(html[data-motion='reduced']) .player-controls button{transition:none}
 @media(prefers-reduced-motion:reduce){.back,.player-controls,.player-controls button{transition:none}}
 .playback-error{position:absolute;color:#e5e5eb;background:#171720;padding:12px 18px;border-radius:8px}
 button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 button:disabled{opacity:.45}
</style>
