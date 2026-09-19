import type { ComponentType, SvelteComponent } from 'svelte';

export interface SettingSearchItem {
  id: string;
  section: string;
  label: string;
  description: string;
  keywords: string[];
}

export interface SettingsContribution {
  group: { id: string; label: string; module: string | null };
  order: number;
  component: ComponentType<SvelteComponent<{ selectedSection: string; query?: string }>>;
  sections: { id: string; group: string; label: string; icon: string }[];
  searchItems: SettingSearchItem[];
}
