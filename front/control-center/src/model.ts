import type { SettingChange, SettingsSchema, SettingsSnapshot } from './types'

export function collectSettingChanges(
  schema: SettingsSchema,
  original: SettingsSnapshot,
  draft: SettingsSnapshot,
): SettingChange[] {
  const result: SettingChange[] = []
  for (const [category, group] of Object.entries(schema)) {
    for (const key of Object.keys(group.items)) {
      const before = original[category]?.[key]
      const after = draft[category]?.[key]
      if (JSON.stringify(before) !== JSON.stringify(after)) {
        result.push({ category, key, value: after })
      }
    }
  }
  return result
}

export function movePluginOrder(
  order: string[],
  pluginId: string,
  direction: -1 | 1,
): string[] | null {
  const next = [...order]
  const index = next.indexOf(pluginId)
  const nextIndex = index + direction
  if (index < 0 || nextIndex < 0 || nextIndex >= next.length) return null
  ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
  return next
}
