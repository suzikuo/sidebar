import type { PlatformAdapter } from '../../../src/services/platformAdapter'
import { qtWebChannelAdapter } from '../../../src/services/qtWebChannelAdapter'
import { controlCenterPreviewAdapter } from './previewAdapter'
import type {
  CatalogSnapshot,
  OverviewSnapshot,
  PluginSnapshot,
  SettingChange,
  SettingsSchema,
  SettingsSnapshot,
} from '../types'

export class ControlCenterApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

export const controlCenterAdapter: PlatformAdapter =
  import.meta.env.MODE === 'control-center'
    ? qtWebChannelAdapter
    : controlCenterPreviewAdapter

async function invoke<T>(route: string, payload: Record<string, unknown> = {}): Promise<T> {
  const result = await controlCenterAdapter.invoke<T>(route, payload)
  if (!result.ok) {
    throw new ControlCenterApiError(
      result.code || 'ERROR',
      result.message || '控制中心请求失败。',
    )
  }
  return result.data as T
}

export const controlCenterApi = {
  overview: () => invoke<OverviewSnapshot>('core/control-center/overview'),
  plugins: () => invoke<PluginSnapshot>('core/control-center/plugins'),
  catalog: () => invoke<CatalogSnapshot>('core/control-center/catalog'),
  settings: () => invoke<SettingsSnapshot>('core/settings/snapshot'),
  settingsSchema: () => invoke<SettingsSchema>('core/settings/schema'),
  saveSettings: (changes: SettingChange[]) =>
    invoke<{ changes: SettingChange[] }>('core/settings/batch', { changes }),
  resetSettings: (category?: string) =>
    invoke<SettingsSnapshot>('core/settings/reset', category ? { category } : {}),
  setPluginEnabled: (pluginId: string, enabled: boolean) =>
    invoke<{ message: string }>('core/control-center/plugin-enable', { pluginId, enabled }),
  setPluginOrder: (order: string[]) =>
    invoke<{ order: string[] }>('core/control-center/plugin-order', { order }),
  importPlugin: () =>
    invoke<{ cancelled: boolean; message?: string }>('core/control-center/plugin-import'),
  installCatalogPlugin: (pluginId: string) =>
    invoke<{ message: string }>('core/control-center/catalog-install', { pluginId }),
  uninstallPlugin: (pluginId: string) =>
    invoke<{ message: string }>('core/control-center/plugin-uninstall', { pluginId }),
  rollbackPlugin: (pluginId: string) =>
    invoke<{ message: string }>('core/control-center/plugin-rollback', { pluginId }),
  cancelPluginChange: (pluginId: string) =>
    invoke<{ message: string }>('core/control-center/plugin-cancel', { pluginId }),
  openDataDirectory: () => invoke<{ opened: boolean }>('core/control-center/open-data'),
  restart: () => invoke<{ scheduled: boolean }>('core/control-center/restart'),
  subscribe: controlCenterAdapter.subscribe.bind(controlCenterAdapter),
}
