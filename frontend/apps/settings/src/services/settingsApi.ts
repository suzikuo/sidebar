import type { SettingsSnapshot, SettingWriteResult } from '../types'
import { platformAdapter } from './platformAdapter'

export class SettingsApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

function unwrap<T>(result: Awaited<ReturnType<typeof platformAdapter.invoke<T>>>): T {
  if (!result.ok) {
    throw new SettingsApiError(result.code || 'ERROR', result.message || '设置请求失败。')
  }
  return result.data as T
}

export const settingsApi = {
  async snapshot(): Promise<SettingsSnapshot> {
    return unwrap(
      await platformAdapter.invoke<SettingsSnapshot>('core/settings/snapshot', {}),
    )
  },

  async set(category: string, key: string, value: unknown): Promise<SettingWriteResult> {
    return unwrap(
      await platformAdapter.invoke<SettingWriteResult>('core/settings/set', {
        category,
        key,
        value,
      }),
    )
  },
}
