<script lang="ts">
  import {onMount} from 'svelte';
  import type {Format,MarkdownEngine} from './markdownEngine';
  import EditorContextMenu from './EditorContextMenu.svelte';
  import type {EditorMenu} from './markdownEngine';

  export let value:string;
  export let label:string;
  export let onChange:(text:string)=>void;
  let host:HTMLDivElement;
  let engine:MarkdownEngine|undefined;
  let loading=true;
  let menu:EditorMenu|null=null;
  let menuSerial=0;

  export function format(kind:Format){engine?.format(kind);}

  onMount(()=>{
    let mounted=true;
    void import('./markdownEngine').then(module=>{
      if(!mounted)return;
      engine=module.mountMarkdownEditor(host,value,label,onChange,context=>{menu=context;menuSerial++;});
      loading=false;
    });
    return ()=>{mounted=false;engine?.destroy();};
  });
</script>

<div class="markdown-editor" bind:this={host}></div>
{#if menu && engine}
  {#key menuSerial}
    <EditorContextMenu context={menu} action={engine.contextAction} close={restore=>{menu=null;engine?.closeContext(restore);}} />
  {/key}
{/if}
{#if loading}<p class="loading-editor" role="status">Loading Markdown editor…</p>{/if}

<style>
  .markdown-editor{min-height:0;flex:1;overflow:hidden}
  .loading-editor{padding:16px;color:#a7a7b6;font-size:12px}
  @media(max-width:600px){.markdown-editor :global(.cm-content){padding:16px}}
</style>
