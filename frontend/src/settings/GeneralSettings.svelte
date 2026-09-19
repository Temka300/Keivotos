<script lang="ts">
  import { getContext } from 'svelte';
  import { SETTINGS_SESSION, type SettingsSession } from '../lib/settingsSession';
  import { compactSegmentClass } from '../lib/settingsControls';
  import { SUITE_NAME } from '../lib/product';
  import { enabledModules, interfaceScale, motionPreference, startupModule, suiteModules } from '../lib/suiteStores';
  import type { InterfaceScale, MotionPreference, StartupModule } from '../lib/suiteStores';
  import BackupRestoreSettings from '../components/BackupRestoreSettings.svelte';
  import ThumbnailCacheSettings from '../components/ThumbnailCacheSettings.svelte';
  export let selectedSection: string;
  export let query = '';
  const session = getContext<SettingsSession>(SETTINGS_SESSION);
  const busyOwners = session.busyOwners;
  $: toolRunning = $busyOwners.size > 0;
  $: startupModuleOptions = [
    { value: 'files' as StartupModule, label: 'Files' },
    ...$suiteModules.filter(module => !module.is_base && $enabledModules.includes(module.id))
      .map(module => ({ value: module.slug as StartupModule, label: module.name })),
    { value: 'last' as StartupModule, label: 'Last used' },
  ];
  const motionOptions: { value: MotionPreference; label: string }[] = [
    { value: 'system', label: 'System' },
    { value: 'full', label: 'Full' },
    { value: 'reduced', label: 'Reduced' },
  ];

  const interfaceScaleOptions: { value: InterfaceScale; label: string }[] = [
    { value: 'default', label: 'Default' },
    { value: 'comfortable', label: 'Comfortable' },
  ];

</script>

{#if !query}
{#if selectedSection === 'appearance'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-motion" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Interface motion</div>
                  <div class="flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each motionOptions as option}<button class={compactSegmentClass($motionPreference === option.value)} type="button" on:click={() => motionPreference.set(option.value)}>{option.label}</button>{/each}</div>
                </div>
                <div id="setting-interface-scale" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div class="text-sm font-medium text-gray-200">Interface scale</div>
                  <div class="flex divide-x divide-[#303040] overflow-hidden rounded-lg border border-[#303040]">{#each interfaceScaleOptions as option}<button class={compactSegmentClass($interfaceScale === option.value)} type="button" on:click={() => interfaceScale.set(option.value)}>{option.label}</button>{/each}</div>
                </div>
              </div>
            </section>
          </div>
{:else if selectedSection === 'startup'}
          <div class="mx-auto max-w-3xl space-y-4">
            <section class="overflow-hidden rounded-xl border border-[#292938] bg-[#111118]">
              <div class="divide-y divide-[#22222e]">
                <div id="setting-startup-module" class="flex items-center justify-between gap-5 px-4 py-3">
                  <div>
                    <div class="text-sm font-medium text-gray-200">Startup destination</div>
                    <div class="mt-0.5 text-xs text-gray-500">Which surface opens when {SUITE_NAME} launches.</div>
                  </div>
                  <select class="w-40 shrink-0 rounded-lg border border-[#303040] bg-[#0d0d13] px-3 py-2 text-xs text-gray-200 outline-none focus:border-purple-400/60" value={$startupModule} on:change={(event) => startupModule.set((event.currentTarget as HTMLSelectElement).value as StartupModule)}>
                    {#each startupModuleOptions as option}<option value={option.value}>{option.label}</option>{/each}
                  </select>
                </div>
              </div>
            </section>
          </div>
{:else if selectedSection === 'storage'}
          <div class="mx-auto max-w-3xl space-y-4">
            <ThumbnailCacheSettings />
          </div>
{:else if selectedSection === 'backup'}
          <div class="mx-auto max-w-3xl space-y-4">
            <BackupRestoreSettings {toolRunning} />
          </div>

{/if}
{/if}
