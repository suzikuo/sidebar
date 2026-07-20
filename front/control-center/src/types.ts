export interface ApiResult<T> {
  ok: boolean
  data?: T
  code?: string
  message?: string
}

export type SettingsSnapshot = Record<string, Record<string, unknown>>

export interface SettingOption {
  value: string
  label: string
}

export interface SettingDefinition {
  label: string
  description: string
  control: 'toggle' | 'segmented' | 'color' | 'range' | 'number' | 'text' | 'select' | 'shortcut'
  default: unknown
  minimum?: number
  maximum?: number
  step?: number
  unit?: string
  format?: 'percent'
  maximumLength?: number
  options?: SettingOption[]
}

export interface SettingGroup {
  title: string
  description: string
  items: Record<string, SettingDefinition>
}

export type SettingsSchema = Record<string, SettingGroup>

export interface SettingChange {
  category: string
  key: string
  value: unknown
}

export interface OverviewSnapshot {
  version: string
  pluginCount: number
  enabledPluginCount: number
  loadedPluginCount: number
  pendingRestartCount: number
  errorCount: number
  errors: Array<{ source: string; message: string }>
}

export interface PluginTransaction {
  operation: string
  state: string
  version: string | null
  generation: number | null
  loadVerified: boolean | null
  errorCode: string | null
  errorMessage: string | null
  requiresRestart: boolean
}

export interface PluginStatus {
  pluginId: string
  name: string
  selectedVersion: string | null
  source: string
  enabled: boolean
  userPresent: boolean
  userVersion: string | null
  loaded: boolean
  canUninstall: boolean
  canRollback: boolean
  restartRequired: boolean
  updateError: string | null
  compatibilityError: string | null
  blockedCode: string | null
  blockedReason: string | null
  blockingDependents: string[]
  transaction: PluginTransaction | null
}

export interface PluginSnapshot {
  order: string[]
  plugins: PluginStatus[]
}

export type CatalogAction = 'install' | 'update' | 'installed' | 'pending' | 'incompatible' | 'older'

export interface CatalogEntry {
  pluginId: string
  name: string
  version: string
  author: string
  description: string
  category: string
  compatible: boolean
  compatibilityCode: string | null
  compatibilityMessage: string | null
  installedVersion: string | null
  enabled: boolean
  restartRequired: boolean
  action: CatalogAction
}

export interface CatalogSnapshot {
  entries: CatalogEntry[]
  errors: Array<{ package: string; code: string; message: string }>
}
