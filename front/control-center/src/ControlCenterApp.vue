<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Blocks,
  CheckCircle2,
  Download,
  FolderOpen,
  History,
  Info,
  LayoutDashboard,
  PackageOpen,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  Store,
  Trash2,
  Upload,
  X,
} from '@lucide/vue'

import { controlCenterApi } from './services/controlCenterApi'
import { collectSettingChanges, movePluginOrder } from './model'
import type {
  CatalogAction,
  CatalogEntry,
  CatalogSnapshot,
  OverviewSnapshot,
  PluginSnapshot,
  PluginStatus,
  SettingChange,
  SettingDefinition,
  SettingsSchema,
  SettingsSnapshot,
} from './types'

type ViewId = 'overview' | 'settings' | 'plugins' | 'market' | 'about'
type LoadState = 'loading' | 'ready' | 'error'

const navigation = [
  { id: 'overview' as ViewId, label: '概览', icon: LayoutDashboard },
  { id: 'settings' as ViewId, label: '设置', icon: Settings },
  { id: 'plugins' as ViewId, label: '已安装插件', icon: Blocks },
  { id: 'market' as ViewId, label: '官方市场', icon: Store },
  { id: 'about' as ViewId, label: '关于与诊断', icon: Info },
]

const loadState = ref<LoadState>('loading')
const initialView = navigation.some((item) => item.id === window.location.hash.slice(1))
  ? window.location.hash.slice(1) as ViewId
  : 'overview'
const activeView = ref<ViewId>(initialView)
const errorMessage = ref('')
const toast = ref('')
const busyAction = ref('')
const overview = ref<OverviewSnapshot | null>(null)
const pluginSnapshot = ref<PluginSnapshot>({ order: [], plugins: [] })
const catalog = ref<CatalogSnapshot>({ entries: [], errors: [] })
const settingsSchema = ref<SettingsSchema>({})
const originalSettings = ref<SettingsSnapshot>({})
const draftSettings = ref<SettingsSnapshot>({})
const pluginSearch = ref('')
const marketSearch = ref('')
const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
const systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)')
let toastTimer: number | undefined
let settingsReloadTimer: number | undefined
const unsubscribers: Array<() => void> = []

const activeTitle = computed(
  () => navigation.find((item) => item.id === activeView.value)?.label || '控制中心',
)

const changes = computed<SettingChange[]>(() => {
  return collectSettingChanges(
    settingsSchema.value,
    originalSettings.value,
    draftSettings.value,
  )
})

const isDirty = computed(() => changes.value.length > 0)
const themeMode = computed(() => String(draftSettings.value.appearance?.theme_mode || 'system'))
const effectiveTheme = computed<'light' | 'dark'>(() =>
  themeMode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : themeMode.value as 'light' | 'dark',
)
const accentColor = computed(() => String(draftSettings.value.appearance?.accent_color || '#FF6B9D'))

const installedPlugins = computed(() => {
  const query = pluginSearch.value.trim().toLocaleLowerCase()
  const index = new Map(pluginSnapshot.value.order.map((pluginId, order) => [pluginId, order]))
  return [...pluginSnapshot.value.plugins]
    .filter((plugin) => plugin.selectedVersion)
    .filter((plugin) => !query || `${plugin.name} ${plugin.pluginId}`.toLocaleLowerCase().includes(query))
    .sort((left, right) => (index.get(left.pluginId) ?? 9999) - (index.get(right.pluginId) ?? 9999))
})

const marketEntries = computed(() => {
  const query = marketSearch.value.trim().toLocaleLowerCase()
  return catalog.value.entries.filter((entry) =>
    !query || `${entry.name} ${entry.pluginId} ${entry.category} ${entry.description}`.toLocaleLowerCase().includes(query),
  )
})

watch([effectiveTheme, accentColor], () => {
  document.documentElement.dataset.theme = effectiveTheme.value
  document.documentElement.style.setProperty('--accent', accentColor.value)
}, { immediate: true })

watch(activeView, (view) => {
  window.history.replaceState(null, '', `#${view}`)
})

onMounted(() => {
  systemThemeQuery.addEventListener('change', onSystemThemeChange)
  unsubscribers.push(
    controlCenterApi.subscribe('settings.changed', scheduleSettingsReload),
    controlCenterApi.subscribe('plugins.changed', () => void loadPluginData()),
  )
  void loadAll()
})

onBeforeUnmount(() => {
  systemThemeQuery.removeEventListener('change', onSystemThemeChange)
  unsubscribers.forEach((unsubscribe) => unsubscribe())
  if (toastTimer) window.clearTimeout(toastTimer)
  if (settingsReloadTimer) window.clearTimeout(settingsReloadTimer)
})

function clone<T>(value: T): T {
  return structuredClone(value)
}

function onSystemThemeChange(event: MediaQueryListEvent) {
  systemDark.value = event.matches
}

function showToast(message: string) {
  toast.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 3000)
}

async function loadAll() {
  loadState.value = 'loading'
  errorMessage.value = ''
  try {
    const [nextOverview, nextPlugins, nextCatalog, schema, settings] = await Promise.all([
      controlCenterApi.overview(),
      controlCenterApi.plugins(),
      controlCenterApi.catalog(),
      controlCenterApi.settingsSchema(),
      controlCenterApi.settings(),
    ])
    overview.value = nextOverview
    pluginSnapshot.value = nextPlugins
    catalog.value = nextCatalog
    settingsSchema.value = schema
    originalSettings.value = clone(settings)
    draftSettings.value = clone(settings)
    loadState.value = 'ready'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
    loadState.value = 'error'
  }
}

async function loadSettings() {
  const settings = await controlCenterApi.settings()
  originalSettings.value = clone(settings)
  draftSettings.value = clone(settings)
}

function scheduleSettingsReload() {
  if (settingsReloadTimer) window.clearTimeout(settingsReloadTimer)
  settingsReloadTimer = window.setTimeout(() => {
    settingsReloadTimer = undefined
    void loadSettings()
  }, 80)
}

async function loadPluginData() {
  const [nextOverview, nextPlugins, nextCatalog] = await Promise.all([
    controlCenterApi.overview(),
    controlCenterApi.plugins(),
    controlCenterApi.catalog(),
  ])
  overview.value = nextOverview
  pluginSnapshot.value = nextPlugins
  catalog.value = nextCatalog
}

function settingValue(category: string, key: string) {
  return draftSettings.value[category]?.[key]
}

function setSetting(category: string, key: string, value: unknown) {
  if (!draftSettings.value[category]) draftSettings.value[category] = {}
  draftSettings.value[category][key] = value
}

function updateFromInput(category: string, key: string, event: Event, kind: 'boolean' | 'number' | 'string') {
  const input = event.target as HTMLInputElement
  const value = kind === 'boolean' ? input.checked : kind === 'number' ? input.valueAsNumber : input.value
  setSetting(category, key, value)
}

function displaySettingValue(definition: SettingDefinition, value: unknown) {
  if (definition.format === 'percent') return `${Math.round(Number(value) * 100)}%`
  return `${String(value)}${definition.unit ? ` ${definition.unit}` : ''}`
}

async function saveSettings() {
  if (!isDirty.value || busyAction.value) return
  busyAction.value = 'settings-save'
  try {
    await controlCenterApi.saveSettings(changes.value)
    originalSettings.value = clone(draftSettings.value)
    showToast('设置已保存')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    busyAction.value = ''
  }
}

function discardSettings() {
  draftSettings.value = clone(originalSettings.value)
}

async function resetSettings(category?: string) {
  const label = category ? settingsSchema.value[category]?.title : '全部设置'
  if (!window.confirm(`恢复${label}的默认值？`)) return
  busyAction.value = `settings-reset-${category || 'all'}`
  try {
    const settings = await controlCenterApi.resetSettings(category)
    originalSettings.value = clone(settings)
    draftSettings.value = clone(settings)
    showToast(`${label}已恢复默认值`)
  } finally {
    busyAction.value = ''
  }
}

async function runPluginAction(actionId: string, operation: () => Promise<unknown>, message?: string) {
  if (busyAction.value) return
  busyAction.value = actionId
  errorMessage.value = ''
  try {
    await operation()
    await loadPluginData()
    showToast(message || '插件操作已完成')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    busyAction.value = ''
  }
}

async function togglePlugin(plugin: PluginStatus, enabled: boolean) {
  await runPluginAction(
    `enable-${plugin.pluginId}`,
    () => controlCenterApi.setPluginEnabled(plugin.pluginId, enabled),
    enabled ? `${plugin.name} 已启用` : `${plugin.name} 已禁用`,
  )
}

async function movePlugin(pluginId: string, direction: -1 | 1) {
  const order = movePluginOrder(pluginSnapshot.value.order, pluginId, direction)
  if (!order) return
  await runPluginAction('plugin-order', () => controlCenterApi.setPluginOrder(order), '插件顺序已更新')
}

async function importPlugin() {
  if (busyAction.value) return
  busyAction.value = 'plugin-import'
  try {
    const result = await controlCenterApi.importPlugin()
    if (!result.cancelled) {
      await loadPluginData()
      showToast(result.message || '插件已加入安装队列')
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    busyAction.value = ''
  }
}

async function confirmPluginAction(plugin: PluginStatus, kind: 'uninstall' | 'rollback' | 'cancel') {
  const labels = { uninstall: '卸载', rollback: '回滚', cancel: '取消待处理变更' }
  if (!window.confirm(`${labels[kind]} ${plugin.name}？相关变更可能需要重启后生效。`)) return
  const operation = kind === 'uninstall'
    ? () => controlCenterApi.uninstallPlugin(plugin.pluginId)
    : kind === 'rollback'
      ? () => controlCenterApi.rollbackPlugin(plugin.pluginId)
      : () => controlCenterApi.cancelPluginChange(plugin.pluginId)
  await runPluginAction(`${kind}-${plugin.pluginId}`, operation)
}

async function installCatalogEntry(entry: CatalogEntry) {
  if (!['install', 'update'].includes(entry.action)) return
  await runPluginAction(
    `catalog-${entry.pluginId}`,
    () => controlCenterApi.installCatalogPlugin(entry.pluginId),
    `${entry.name} 已加入安装队列`,
  )
}

async function restartApplication() {
  if (!window.confirm('立即重启 Agile Tiles？')) return
  await controlCenterApi.restart()
  showToast('正在重启')
}

async function openDataDirectory() {
  try {
    await controlCenterApi.openDataDirectory()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

function pluginRuntimeLabel(plugin: PluginStatus) {
  if (plugin.blockedReason) return '已阻止'
  if (!plugin.enabled) return '已禁用'
  return plugin.loaded ? '运行中' : '未加载'
}

function transactionLabel(plugin: PluginStatus) {
  const state = plugin.transaction?.state
  return ({ pending: '等待重启', rollback_pending: '回滚等待重启', failed: '操作失败', applied: '已应用', rolled_back: '已回滚' } as Record<string, string>)[state || ''] || state
}

function catalogActionLabel(action: CatalogAction) {
  return ({ install: '安装', update: '更新', installed: '已安装', pending: '等待重启', incompatible: '不兼容', older: '本机版本较新' } as Record<CatalogAction, string>)[action]
}
</script>

<template>
  <div class="control-center-shell">
    <aside class="app-navigation">
      <div class="brand-block">
        <div class="brand-mark">AT</div>
        <div>
          <strong>Agile Tiles</strong>
          <span>控制中心</span>
        </div>
      </div>

      <nav aria-label="控制中心导航">
        <button
          v-for="item in navigation"
          :key="item.id"
          type="button"
          :title="item.label"
          :class="{ active: activeView === item.id }"
          @click="activeView = item.id"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
          <span v-if="item.id === 'overview' && overview?.pendingRestartCount" class="nav-count">{{ overview.pendingRestartCount }}</span>
        </button>
      </nav>

      <div class="navigation-footer">
        <span>v{{ overview?.version || '...' }}</span>
        <span :class="['connection-state', loadState]">{{ loadState === 'ready' ? '已连接' : loadState === 'loading' ? '连接中' : '连接失败' }}</span>
      </div>
    </aside>

    <main class="main-workspace">
      <header class="workspace-header">
        <div>
          <h1>{{ activeTitle }}</h1>
          <p v-if="activeView === 'overview'">应用状态与待处理事项</p>
          <p v-else-if="activeView === 'settings'">完整应用设置</p>
          <p v-else-if="activeView === 'plugins'">运行状态、顺序与生命周期</p>
          <p v-else-if="activeView === 'market'">发行版附带的已验证插件包</p>
          <p v-else>版本、目录与错误信息</p>
        </div>
        <button class="icon-button" type="button" title="刷新" :disabled="loadState === 'loading'" @click="loadAll">
          <RefreshCw :size="18" :class="{ spin: loadState === 'loading' }" />
        </button>
      </header>

      <div v-if="errorMessage" class="global-error" role="alert">
        <AlertTriangle :size="18" />
        <span>{{ errorMessage }}</span>
        <button type="button" title="关闭" @click="errorMessage = ''"><X :size="16" /></button>
      </div>

      <section v-if="loadState === 'loading'" class="loading-state" aria-live="polite">
        <div v-for="index in 6" :key="index" class="loading-line" />
      </section>

      <section v-else-if="loadState === 'error'" class="empty-state">
        <AlertTriangle :size="28" />
        <h2>控制中心数据加载失败</h2>
        <p>{{ errorMessage }}</p>
        <button class="button primary" type="button" @click="loadAll">重试</button>
      </section>

      <div v-else class="workspace-content">
        <section v-if="activeView === 'overview' && overview" class="overview-view">
          <div v-if="overview.pendingRestartCount" class="restart-banner">
            <div>
              <RefreshCw :size="20" />
              <span><strong>{{ overview.pendingRestartCount }}</strong> 项插件变更等待重启</span>
            </div>
            <button class="button primary" type="button" @click="restartApplication">立即重启</button>
          </div>

          <div class="metric-grid">
            <article>
              <span>已安装插件</span>
              <strong>{{ overview.pluginCount }}</strong>
              <small>{{ overview.enabledPluginCount }} 个已启用</small>
            </article>
            <article>
              <span>运行中</span>
              <strong>{{ overview.loadedPluginCount }}</strong>
              <small>当前已加载</small>
            </article>
            <article>
              <span>待重启</span>
              <strong>{{ overview.pendingRestartCount }}</strong>
              <small>插件事务</small>
            </article>
            <article>
              <span>错误</span>
              <strong>{{ overview.errorCount }}</strong>
              <small>加载与更新</small>
            </article>
          </div>

          <section class="workspace-section">
            <div class="section-title-row">
              <div><h2>运行状态</h2><p>插件与宿主状态摘要</p></div>
            </div>
            <div class="status-list">
              <button type="button" @click="activeView = 'plugins'">
                <Blocks :size="18" /><span>插件</span><strong>{{ overview.enabledPluginCount }}/{{ overview.pluginCount }} 已启用</strong>
              </button>
              <button type="button" @click="activeView = 'market'">
                <Store :size="18" /><span>官方市场</span><strong>{{ catalog.entries.length }} 个可用包</strong>
              </button>
              <button type="button" @click="activeView = 'settings'">
                <Settings :size="18" /><span>设置</span><strong>{{ isDirty ? `${changes.length} 项未保存` : '已同步' }}</strong>
              </button>
            </div>
          </section>

          <section class="workspace-section">
            <div class="section-title-row"><div><h2>最近错误</h2><p>最多显示 20 项</p></div></div>
            <div v-if="overview.errors.length" class="diagnostic-list">
              <div v-for="error in overview.errors" :key="`${error.source}-${error.message}`">
                <AlertTriangle :size="17" /><strong>{{ error.source }}</strong><span>{{ error.message }}</span>
              </div>
            </div>
            <div v-else class="inline-empty"><CheckCircle2 :size="19" />当前没有插件加载或更新错误</div>
          </section>
        </section>

        <section v-else-if="activeView === 'settings'" class="settings-view">
          <div class="settings-toolbar">
            <span>{{ changes.length }} 项更改</span>
            <div>
              <button class="button subtle" type="button" :disabled="!isDirty || !!busyAction" @click="discardSettings">撤销</button>
              <button class="button subtle danger" type="button" :disabled="!!busyAction" @click="resetSettings()"><RotateCcw :size="16" />全部恢复默认</button>
              <button class="button primary" type="button" :disabled="!isDirty || !!busyAction" @click="saveSettings">保存更改</button>
            </div>
          </div>

          <section v-for="(group, category) in settingsSchema" :key="category" class="settings-group">
            <div class="section-title-row">
              <div><h2>{{ group.title }}</h2><p>{{ group.description }}</p></div>
              <button class="icon-button" type="button" :title="`恢复${group.title}默认值`" :disabled="!!busyAction" @click="resetSettings(String(category))"><RotateCcw :size="16" /></button>
            </div>

            <div v-for="(definition, key) in group.items" :key="key" class="setting-row">
              <div class="setting-copy"><strong>{{ definition.label }}</strong><span>{{ definition.description }}</span></div>

              <label v-if="definition.control === 'toggle'" class="toggle-control">
                <input type="checkbox" :checked="Boolean(settingValue(String(category), String(key)))" @change="updateFromInput(String(category), String(key), $event, 'boolean')" />
                <span />
              </label>

              <div v-else-if="definition.control === 'segmented'" class="segmented-control">
                <button v-for="option in definition.options" :key="option.value" type="button" :class="{ active: settingValue(String(category), String(key)) === option.value }" @click="setSetting(String(category), String(key), option.value)">{{ option.label }}</button>
              </div>

              <div v-else-if="definition.control === 'color'" class="color-control">
                <input type="color" :value="String(settingValue(String(category), String(key)))" :aria-label="definition.label" @input="updateFromInput(String(category), String(key), $event, 'string')" />
                <code>{{ settingValue(String(category), String(key)) }}</code>
              </div>

              <div v-else-if="definition.control === 'range'" class="range-control">
                <input type="range" :min="definition.minimum" :max="definition.maximum" :step="definition.step" :value="Number(settingValue(String(category), String(key)))" @input="updateFromInput(String(category), String(key), $event, 'number')" />
                <output>{{ displaySettingValue(definition, settingValue(String(category), String(key))) }}</output>
              </div>

              <div v-else-if="definition.control === 'number'" class="number-control">
                <input type="number" :min="definition.minimum" :max="definition.maximum" :step="definition.step" :value="Number(settingValue(String(category), String(key)))" @input="updateFromInput(String(category), String(key), $event, 'number')" />
                <span>{{ definition.unit }}</span>
              </div>

              <select v-else-if="definition.control === 'select'" class="select-control" :value="String(settingValue(String(category), String(key)))" @change="updateFromInput(String(category), String(key), $event, 'string')">
                <option v-for="option in definition.options" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>

              <input v-else class="text-control" :value="String(settingValue(String(category), String(key)))" :maxlength="definition.maximumLength" @input="updateFromInput(String(category), String(key), $event, 'string')" />
            </div>
          </section>
        </section>

        <section v-else-if="activeView === 'plugins'" class="plugins-view">
          <div class="list-toolbar">
            <label class="search-control"><Search :size="17" /><input v-model="pluginSearch" placeholder="搜索已安装插件" /></label>
            <button class="button primary" type="button" :disabled="!!busyAction" @click="importPlugin"><Upload :size="16" />导入插件包</button>
          </div>

          <div v-if="installedPlugins.length" class="plugin-list">
            <article v-for="plugin in installedPlugins" :key="plugin.pluginId" class="plugin-row">
              <div class="plugin-icon"><PackageOpen :size="20" /></div>
              <div class="plugin-main">
                <div><strong>{{ plugin.name }}</strong><code>{{ plugin.pluginId }}</code></div>
                <span>v{{ plugin.selectedVersion }} · {{ pluginRuntimeLabel(plugin) }}</span>
                <p v-if="plugin.blockedReason" class="row-error">{{ plugin.blockedReason }}</p>
                <p v-else-if="plugin.updateError || plugin.compatibilityError" class="row-error">{{ plugin.updateError || plugin.compatibilityError }}</p>
              </div>
              <div class="plugin-state">
                <span v-if="plugin.transaction" class="status-badge warning">{{ transactionLabel(plugin) }}</span>
                <span v-else :class="['status-badge', plugin.loaded ? 'success' : 'neutral']">{{ pluginRuntimeLabel(plugin) }}</span>
              </div>
              <div class="row-actions">
                <button class="icon-button" type="button" title="上移" :disabled="pluginSnapshot.order.indexOf(plugin.pluginId) <= 0 || !!busyAction" @click="movePlugin(plugin.pluginId, -1)"><ArrowUp :size="16" /></button>
                <button class="icon-button" type="button" title="下移" :disabled="pluginSnapshot.order.indexOf(plugin.pluginId) >= pluginSnapshot.order.length - 1 || !!busyAction" @click="movePlugin(plugin.pluginId, 1)"><ArrowDown :size="16" /></button>
                <button v-if="plugin.transaction?.requiresRestart" class="icon-button" type="button" title="取消待处理变更" :disabled="!!busyAction" @click="confirmPluginAction(plugin, 'cancel')"><X :size="16" /></button>
                <button v-if="plugin.canRollback" class="icon-button" type="button" title="回滚" :disabled="!!busyAction" @click="confirmPluginAction(plugin, 'rollback')"><History :size="16" /></button>
                <button v-if="plugin.userPresent" class="icon-button danger" type="button" :title="plugin.blockingDependents.length ? `被以下插件依赖：${plugin.blockingDependents.join(', ')}` : '卸载'" :disabled="!plugin.canUninstall || !!busyAction" @click="confirmPluginAction(plugin, 'uninstall')"><Trash2 :size="16" /></button>
                <label class="toggle-control compact" :title="plugin.enabled ? '禁用插件' : '启用插件'">
                  <input type="checkbox" :checked="plugin.enabled" :disabled="!!busyAction" @change="togglePlugin(plugin, ($event.target as HTMLInputElement).checked)" />
                  <span />
                </label>
              </div>
            </article>
          </div>
          <div v-else class="inline-empty">没有匹配的已安装插件</div>
        </section>

        <section v-else-if="activeView === 'market'" class="market-view">
          <div class="list-toolbar">
            <label class="search-control"><Search :size="17" /><input v-model="marketSearch" placeholder="搜索官方插件" /></label>
            <span class="catalog-source">本地官方包 · {{ catalog.entries.length }}</span>
          </div>

          <div v-if="marketEntries.length" class="market-list">
            <article v-for="entry in marketEntries" :key="entry.pluginId" class="market-row">
              <div class="market-icon"><Download :size="20" /></div>
              <div class="market-main">
                <div><strong>{{ entry.name }}</strong><span>{{ entry.category }}</span></div>
                <p>{{ entry.description || '暂无描述' }}</p>
                <small>v{{ entry.version }}<template v-if="entry.author"> · {{ entry.author }}</template><template v-if="entry.installedVersion"> · 已安装 v{{ entry.installedVersion }}</template></small>
              </div>
              <div class="market-action">
                <span v-if="entry.compatibilityMessage" class="compatibility-message">{{ entry.compatibilityMessage }}</span>
                <button :class="['button', ['install', 'update'].includes(entry.action) ? 'primary' : 'subtle']" type="button" :disabled="!['install', 'update'].includes(entry.action) || !!busyAction" @click="installCatalogEntry(entry)">{{ catalogActionLabel(entry.action) }}</button>
              </div>
            </article>
          </div>
          <div v-else class="inline-empty">官方插件目录为空</div>

          <div v-if="catalog.errors.length" class="catalog-errors">
            <div v-for="error in catalog.errors" :key="error.package"><AlertTriangle :size="16" /><span>{{ error.package }}：{{ error.message }}</span></div>
          </div>
        </section>

        <section v-else class="about-view">
          <section class="workspace-section about-summary">
            <div class="about-mark">AT</div>
            <div><h2>Agile Tiles</h2><p>版本 {{ overview?.version || 'unknown' }}</p></div>
            <button class="button subtle" type="button" @click="openDataDirectory"><FolderOpen :size="16" />打开数据目录</button>
          </section>

          <section class="workspace-section">
            <div class="section-title-row"><div><h2>运行信息</h2><p>当前宿主与插件状态</p></div></div>
            <dl class="facts-list">
              <div><dt>应用版本</dt><dd>{{ overview?.version }}</dd></div>
              <div><dt>插件</dt><dd>{{ overview?.loadedPluginCount }}/{{ overview?.pluginCount }} 正在运行</dd></div>
              <div><dt>待重启事务</dt><dd>{{ overview?.pendingRestartCount }}</dd></div>
              <div><dt>错误</dt><dd>{{ overview?.errorCount }}</dd></div>
            </dl>
          </section>

          <section class="workspace-section">
            <div class="section-title-row"><div><h2>诊断</h2><p>插件加载和更新错误</p></div></div>
            <div v-if="overview?.errors.length" class="diagnostic-list">
              <div v-for="error in overview.errors" :key="`${error.source}-${error.message}`"><AlertTriangle :size="17" /><strong>{{ error.source }}</strong><span>{{ error.message }}</span></div>
            </div>
            <div v-else class="inline-empty"><CheckCircle2 :size="19" />没有需要处理的错误</div>
          </section>
        </section>
      </div>
    </main>

    <div v-if="toast" class="toast" role="status"><CheckCircle2 :size="17" />{{ toast }}</div>
  </div>
</template>
