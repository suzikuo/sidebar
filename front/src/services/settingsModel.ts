import type { SettingsSnapshot } from '../types'

export interface SettingChange {
  category: keyof SettingsSnapshot
  key: string
  value: unknown
}

export function cloneSettings(settings: SettingsSnapshot): SettingsSnapshot {
  return structuredClone(settings)
}

export function collectSettingChanges(
  original: SettingsSnapshot,
  draft: SettingsSnapshot,
): SettingChange[] {
  const changes: SettingChange[] = []
  for (const category of Object.keys(draft) as Array<keyof SettingsSnapshot>) {
    const before = original[category] as unknown as Record<string, unknown>
    const after = draft[category] as unknown as Record<string, unknown>
    for (const [key, value] of Object.entries(after)) {
      if (JSON.stringify(before[key]) !== JSON.stringify(value)) {
        changes.push({ category, key, value })
      }
    }
  }
  return changes
}

export function createPreviewSettings(): SettingsSnapshot {
  return {
    general: {
      run_on_startup: false,
      enable_notifications: true,
      auto_hide_delay: 1000,
      trigger_zone_width: 5,
    },
    appearance: {
      theme_mode: 'dark',
      sidebar_position: 'right',
      sidebar_width: 500,
      collapsed_width: 48,
      icon_size: 40,
      font_family: 'Segoe UI',
      font_size: 13,
      font_weight: 'normal',
      accent_color: '#FF6B9D',
      peek_width: 2,
      sidebar_bg_opacity: 0.9,
      detail_bg_opacity: 0.9,
      sidebar_height_percent: 0.8,
      sidebar_hidden_height_percent: 0.8,
      sidebar_y_offset: 0,
      max_plugins_count: 0,
    },
    plugins: { enabled: [], disabled: [] },
    shortcuts: { toggle_sidebar: 'alt+space' },
  }
}
