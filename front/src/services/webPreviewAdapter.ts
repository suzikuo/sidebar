import type { ApiResult, SettingsSnapshot, SettingWriteResult } from '../types'
import type { PlatformAdapter } from './platformAdapter'
import { cloneSettings, createPreviewSettings } from './settingsModel.ts'

let previewSettings = createPreviewSettings()

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data }
}

function fail<T>(code: string, message: string): ApiResult<T> {
  return { ok: false, code, message }
}

export const browserPreviewAdapter: PlatformAdapter = {
  async invoke<T>(route: string, payload: Record<string, unknown> = {}) {
    await Promise.resolve()

    if (route === 'core/settings/snapshot') {
      return ok(cloneSettings(previewSettings)) as ApiResult<T>
    }

    if (route === 'core/settings/set') {
      const category = payload.category
      const key = payload.key
      if (
        typeof category !== 'string' ||
        typeof key !== 'string' ||
        !(category in previewSettings)
      ) {
        return fail('INVALID_REQUEST', '设置项无效。')
      }

      const target = previewSettings[category as keyof SettingsSnapshot] as unknown as Record<
        string,
        unknown
      >
      if (!(key in target) || !('value' in payload)) {
        return fail('INVALID_REQUEST', '设置项无效。')
      }

      target[key] = payload.value
      return ok<SettingWriteResult>({ category, key, value: payload.value }) as ApiResult<T>
    }

    return fail('ROUTE_NOT_FOUND', '预览环境未实现此 API。')
  },
}
