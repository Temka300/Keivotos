<script lang="ts">
  export let label: string;
  export let checked = false;
  export let disabled = false;
</script>
<button type="button" role="switch" aria-label={label} aria-checked={checked} {disabled} on:click class="settings-switch" class:checked>
  <span></span>
</button>
<style>
  .settings-switch{position:relative;width:46px;height:26px;flex-shrink:0;border-radius:999px;background:#2a2a3a;transition:background-color .15s;outline-offset:4px}
  .settings-switch.checked{background:var(--accent, #a53cf0)}
  span{position:absolute;left:3px;top:3px;width:20px;height:20px;background:white;border-radius:50%;transition:transform .15s}
  .checked span{transform:translateX(20px)}
  button:disabled{opacity:.45;cursor:default}
  @media(prefers-reduced-motion:reduce){span,.settings-switch{transition:none}}
</style>
