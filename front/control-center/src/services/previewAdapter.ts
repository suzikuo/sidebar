import type { PlatformAdapter } from '../../../src/services/platformAdapter'
import type { ApiResult } from '../types'
import type {
  CatalogSnapshot,
  OverviewSnapshot,
  PluginSnapshot,
  SettingsSchema,
  SettingsSnapshot,
} from '../types'

const schema: SettingsSchema = {
  general: {
    title: '通用',
    description: '应用启动与侧边栏交互行为。',
    items: {
      run_on_startup: { label: '开机启动', description: '登录后自动启动。', control: 'toggle', default: false },
      enable_mouse_hover: { label: '贴边隐藏与悬停显示', description: '鼠标离开时隐藏。', control: 'toggle', default: true },
      auto_hide_delay: { label: '自动隐藏延迟', description: '鼠标离开后的等待时间。', control: 'number', default: 1000, minimum: 0, maximum: 10000, step: 100, unit: 'ms' },
    },
  },
  notifications: {
    title: '通知',
    description: '控制应用与插件通知。',
    items: {
      enabled: { label: '启用通知', description: '允许显示应用通知。', control: 'toggle', default: true },
    },
  },
  appearance: {
    title: '外观与布局',
    description: '主题、侧边栏尺寸和详情窗口外观。',
    items: {
      theme_mode: { label: '主题模式', description: '选择显示主题。', control: 'segmented', default: 'dark', options: [{ value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }, { value: 'system', label: '系统' }] },
      accent_color: { label: '强调色', description: '选中状态和主要操作颜色。', control: 'color', default: '#FF6B9D' },
      sidebar_position: { label: '侧边栏位置', description: '选择停靠边缘。', control: 'segmented', default: 'right', options: [{ value: 'left', label: '左侧' }, { value: 'right', label: '右侧' }, { value: 'top', label: '顶部' }] },
      sidebar_width: { label: '展开宽度', description: '侧边栏展开后的宽度。', control: 'range', default: 500, minimum: 320, maximum: 1200, step: 10, unit: 'px' },
      sidebar_bg_opacity: { label: '侧边栏不透明度', description: '侧边栏背景不透明度。', control: 'range', default: 0.9, minimum: 0.1, maximum: 1, step: 0.05, format: 'percent' },
      detail_min_height: { label: '详情页最小高度', description: '插件详情窗口的最小高度。', control: 'range', default: 700, minimum: 300, maximum: 1200, step: 10, unit: 'px' },
      sidebar_border_color: { label: '隐藏边框颜色', description: '屏幕边缘提示颜色。', control: 'color', default: '#FF0000' },
      font_family: { label: '字体', description: '界面字体。', control: 'text', default: 'Segoe UI', maximumLength: 128 },
    },
  },
  shortcuts: {
    title: '快捷键',
    description: '全局操作快捷键。',
    items: {
      toggle_sidebar: { label: '显示/隐藏侧边栏', description: '切换侧边栏状态。', control: 'shortcut', default: 'alt+space', maximumLength: 128 },
    },
  },
}

let settings: SettingsSnapshot = Object.fromEntries(
  Object.entries(schema).map(([category, group]) => [
    category,
    Object.fromEntries(Object.entries(group.items).map(([key, item]) => [key, item.default])),
  ]),
)

let plugins: PluginSnapshot = {
  order: ['time', 'gateway_manager', 'toolbox'],
  plugins: [
    {
      pluginId: 'time', name: '时间', selectedVersion: '1.0.0', source: 'user', enabled: true, userPresent: true, userVersion: '1.0.0', loaded: true, canUninstall: true, canRollback: false, restartRequired: false, updateError: null, compatibilityError: null, blockedCode: null, blockedReason: null, blockingDependents: [], transaction: null,
    },
    {
      pluginId: 'gateway_manager', name: '网关管理', selectedVersion: '1.0.0', source: 'user', enabled: true, userPresent: true, userVersion: '1.0.0', loaded: true, canUninstall: false, canRollback: true, restartRequired: true, updateError: null, compatibilityError: null, blockedCode: null, blockedReason: null, blockingDependents: ['bookmarks.card'], transaction: { operation: 'install', state: 'pending', version: '1.1.0', generation: 2, loadVerified: null, errorCode: null, errorMessage: null, requiresRestart: true },
    },
    {
      pluginId: 'toolbox', name: '工具箱', selectedVersion: '1.0.0', source: 'user', enabled: false, userPresent: true, userVersion: '1.0.0', loaded: false, canUninstall: true, canRollback: false, restartRequired: false, updateError: null, compatibilityError: null, blockedCode: null, blockedReason: null, blockingDependents: [], transaction: null,
    },
  ],
}

const catalog: CatalogSnapshot = {
  entries: [
    { pluginId: 'app_launcher', name: '应用启动器', version: '1.0.0', author: 'Agile Tiles', description: '集中启动常用应用、目录与命令。', category: '效率', compatible: true, compatibilityCode: null, compatibilityMessage: null, installedVersion: null, enabled: false, restartRequired: false, action: 'install' },
    { pluginId: 'gateway_manager', name: '网关管理', version: '1.1.0', author: 'Agile Tiles', description: '管理本地网关、路由和 Cloudflare Tunnel。', category: '网络', compatible: true, compatibilityCode: null, compatibilityMessage: null, installedVersion: '1.0.0', enabled: true, restartRequired: true, action: 'pending' },
    { pluginId: 'ssh_manager', name: 'SSH 管理', version: '1.0.0', author: 'Agile Tiles', description: '管理远程服务器连接。', category: '开发', compatible: true, compatibilityCode: null, compatibilityMessage: null, installedVersion: null, enabled: false, restartRequired: false, action: 'install' },
  ],
  errors: [],
}

function clone<T>(value: T): T {
  return structuredClone(value)
}

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data }
}

function fail<T>(message: string): ApiResult<T> {
  return { ok: false, code: 'PREVIEW_ERROR', message }
}

export const controlCenterPreviewAdapter: PlatformAdapter = {
  async invoke<T>(route: string, payload: Record<string, unknown> = {}) {
    await Promise.resolve()
    if (route === 'core/control-center/overview') {
      return ok<OverviewSnapshot>({ version: '1.0.0', pluginCount: 3, enabledPluginCount: 2, loadedPluginCount: 2, pendingRestartCount: 1, errorCount: 0, errors: [] }) as ApiResult<T>
    }
    if (route === 'core/control-center/plugins') return ok(clone(plugins)) as ApiResult<T>
    if (route === 'core/control-center/catalog') return ok(clone(catalog)) as ApiResult<T>
    if (route === 'core/settings/snapshot') return ok(clone(settings)) as ApiResult<T>
    if (route === 'core/settings/schema') return ok(clone(schema)) as ApiResult<T>
    if (route === 'core/settings/batch') {
      const changes = Array.isArray(payload.changes) ? payload.changes : []
      for (const change of changes as Array<{ category: string; key: string; value: unknown }>) {
        settings[change.category][change.key] = change.value
      }
      return ok({ changes }) as ApiResult<T>
    }
    if (route === 'core/settings/reset') {
      const category = payload.category
      const categories = typeof category === 'string' ? [category] : Object.keys(schema)
      for (const name of categories) {
        settings[name] = Object.fromEntries(Object.entries(schema[name].items).map(([key, item]) => [key, item.default]))
      }
      return ok(clone(settings)) as ApiResult<T>
    }
    if (route === 'core/control-center/plugin-enable') {
      const plugin = plugins.plugins.find((item) => item.pluginId === payload.pluginId)
      if (!plugin || typeof payload.enabled !== 'boolean') return fail('插件不存在。')
      plugin.enabled = payload.enabled
      plugin.loaded = payload.enabled
      return ok({ message: '插件状态已更新。' }) as ApiResult<T>
    }
    if (route === 'core/control-center/plugin-order') {
      plugins.order = [...(payload.order as string[])]
      return ok({ order: plugins.order }) as ApiResult<T>
    }
    if (route === 'core/control-center/plugin-import') return ok({ cancelled: true }) as ApiResult<T>
    if (route.startsWith('core/control-center/plugin-') || route === 'core/control-center/catalog-install') {
      return ok({ message: '操作已加入待处理队列。' }) as ApiResult<T>
    }
    if (route === 'core/control-center/open-data') return ok({ opened: true }) as ApiResult<T>
    if (route === 'core/control-center/restart') return ok({ scheduled: true }) as ApiResult<T>
    return fail('预览环境未实现此操作。')
  },
  subscribe() {
    return () => undefined
  },
}
