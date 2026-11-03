<script lang="ts">
  import {onMount,onDestroy,tick} from 'svelte';
  import type {EditorAction,EditorMenu} from './markdownEngine';

  export let context:EditorMenu;
  export let action:(kind:EditorAction)=>Promise<void>;
  export let close:(restore:boolean)=>void;
  let menu:HTMLDivElement;
  let left=context.x,top=context.y;
  let busy=false,error='';
  let alive=true;
  const actions:[EditorAction,string][]=[['cut','Cut'],['copy','Copy'],['paste','Paste'],['table','Insert table']];

  onMount(async()=>{
    await tick();
    if(!alive)return;
    const bounds=menu.getBoundingClientRect();
    left=Math.max(8,Math.min(left,window.innerWidth-bounds.width-8));
    top=Math.max(8,Math.min(top,window.innerHeight-bounds.height-8));
    menu.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
  });
  onDestroy(()=>{alive=false;});
  function disabled(kind:EditorAction){return busy||((kind==='cut'||kind==='copy')&&!context.selected)||(kind==='table'&&!context.tableAllowed);}
  async function choose(kind:EditorAction){
    if(disabled(kind))return;
    busy=true;error='';
    try{await action(kind);close(true);}
    catch(caught){if(alive)error=caught instanceof Error?caught.message:'Could not complete this editor action.';}
    finally{
      if(alive){
        busy=false;await tick();
        if(alive){
          const bounds=menu.getBoundingClientRect();
          top=Math.max(8,Math.min(top,window.innerHeight-bounds.height-8));
          menu.querySelector<HTMLButtonElement>(`button[data-action="${kind}"]`)?.focus();
        }
      }
    }
  }
  function key(event:KeyboardEvent){
    if(event.key==='Escape'||event.key==='Tab'){event.preventDefault();event.stopPropagation();close(true);return;}
    if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    event.preventDefault();event.stopPropagation();
    const buttons=[...menu.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
    if(!buttons.length)return;
    const index=buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowUp'?-1:1)+buttons.length)%buttons.length;
    buttons[next].focus();
  }
</script>

<svelte:window on:pointerdown={event=>{if(!menu?.contains(event.target as Node))close(false);}} on:resize={()=>close(true)} on:scroll|capture={()=>close(true)} />

<div bind:this={menu} class="editor-menu" role="menu" aria-label="Markdown text actions" tabindex="-1"
  style:left="{left}px" style:top="{top}px" on:keydown={key}>
  {#each actions as [kind,label]}
    <button type="button" role="menuitem" data-action={kind} disabled={disabled(kind)} on:click={()=>choose(kind)}>{label}</button>
  {/each}
  {#if !context.tableAllowed}<p>Move the cursor outside code or HTML to insert a table.</p>{/if}
  {#if error}<p role="alert">{error}</p>{/if}
</div>

<style>
  .editor-menu{position:fixed;z-index:140;width:220px;max-width:calc(100vw - 16px);padding:4px;border:1px solid #2a2a3a;border-radius:10px;background:#1e1e2e;box-shadow:0 8px 24px #0007}
  button{display:block;width:100%;padding:8px 12px;border:0;border-radius:6px;background:none;color:#eee;text-align:left;font-size:13px;cursor:pointer}
  button:hover,button:focus-visible{background:#2a2a3a;outline:1px solid var(--accent)}
  button:disabled{opacity:.4;cursor:default}
  p{padding:4px 8px;color:#f5d5a2;font-size:12px;line-height:1.4}
</style>
