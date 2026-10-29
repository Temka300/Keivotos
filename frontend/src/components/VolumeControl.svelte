<script lang="ts">
  export let value=100;
  export let disabled=false;
  export let onChange:(value:number)=>void;
  let previousVolume=100;
  function change(event:Event){onChange(Number((event.currentTarget as HTMLInputElement).value));}
  function toggleMute(){if(value>0){previousVolume=value;onChange(0);}else onChange(previousVolume);}
</script>

<div class="volume-control">
  <button type="button" class="volume-button" aria-label={value===0?'Unmute':'Mute'} {disabled} on:click={toggleMute}><svg class="volume-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4Z"/>{#if value===0}<path d="m17 9 5 6m0-6-5 6"/>{:else}<path d="M17 9a5 5 0 0 1 0 6"/>{#if value>=50}<path d="M20 6a9 9 0 0 1 0 12"/>{/if}{/if}</svg></button>
  <input aria-label="Volume" aria-valuetext={`${value}%`} type="range" min="0" max="100" step="1" {value} {disabled} style={`--volume:${value}%`} on:input={change}/>
</div>

<style>
  .volume-control{display:flex;align-items:center;gap:8px;width:142px;height:40px;min-width:0;color:#eee}
  .volume-button{display:grid;place-items:center;width:40px;height:40px;flex-shrink:0;padding:0;border:0;border-radius:50%;background:transparent;color:#eee;cursor:pointer;transition:background-color .15s ease}
  .volume-button:hover:not(:disabled){background:#ffffff20}
  .volume-button:disabled{opacity:.45;cursor:default}
  .volume-button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
  .volume-icon{width:24px;height:24px}
  input{appearance:none;flex:1;min-width:0;height:24px;margin:0;padding:0;background:transparent;cursor:pointer}
  input::-webkit-slider-runnable-track{height:3px;border-radius:99px;background:linear-gradient(to right,var(--accent) var(--volume),#ffffff55 var(--volume))}
  input::-moz-range-track{height:3px;border-radius:99px;background:linear-gradient(to right,var(--accent) var(--volume),#ffffff55 var(--volume))}
  input::-webkit-slider-thumb{appearance:none;width:11px;height:11px;margin-top:-4px;border:0;border-radius:50%;background:var(--accent)}
  input::-moz-range-thumb{width:11px;height:11px;border:0;border-radius:50%;background:var(--accent)}
  input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
  input:disabled{opacity:.45;cursor:default}
  @media(max-width:600px){.volume-control{width:110px;gap:4px}.volume-button{width:32px;height:36px}.volume-icon{width:20px;height:20px}}
  @media(max-width:400px){.volume-control{width:94px}.volume-button{width:28px}}
  :global(html[data-motion='reduced']) .volume-button{transition:none}
  @media(prefers-reduced-motion:reduce){.volume-button{transition:none}}
</style>
