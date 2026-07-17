<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { settingsApi } from './services/settingsApi'
import {
  cloneSettings,
  collectSettingChanges,
  type SettingChange,
} from './services/settingsModel'
import type { SettingsSnapshot, ThemeMode } from './types'

type LoadState = 'loading' | 'ready' | 'error'
type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const loadState = ref<LoadState>('loading')
const saveState = ref<SaveState>('idle')
const errorMessage = ref('')
const original = ref<SettingsSnapshot | null>(null)
const draft = ref<SettingsSnapshot | null>(null)
const activeSection = ref('general')
const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
const systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)')
let savedTimer: number | undefined

const changes = computed<SettingChange[]>(() => {
  if (!original.value || !draft.value) return []
  return collectSettingChanges(original.value, draft.value)
})
const isDirty = computed(() => changes.value.length > 0)
const effectiveTheme = computed<'light' | 'dark'>(() => {
  const mode = draft.value?.appearance.theme_mode || 'system'
  return mode === 'system' ? (systemDark.value ? 'dark' : 'light') : mode
})
const accentStyle = computed(() => ({
  '--accent': draft.value?.appearance.accent_color || '#FF6B9D',
}))

watch([effectiveTheme, accentStyle], () => {
  document.documentElement.dataset.theme = effectiveTheme.value
  document.documentElement.style.setProperty(
    '--accent',
    draft.value?.appearance.accent_color || '#FF6B9D',
  )
}, { immediate: true })

watch(isDirty, (dirty) => {
  if (dirty && saveState.value === 'saved') saveState.value = 'idle'
})

onMounted(() => {
  systemThemeQuery.addEventListener('change', onSystemThemeChange)
  void loadSettings()
})

onBeforeUnmount(() => {
  systemThemeQuery.removeEventListener('change', onSystemThemeChange)
  if (savedTimer) window.clearTimeout(savedTimer)
})

function onSystemThemeChange(event: MediaQueryListEvent) {
  systemDark.value = event.matches
}

async function loadSettings() {
  loadState.value = 'loading'
  saveState.value = 'idle'
  errorMessage.value = ''
  try {
    const snapshot = await settingsApi.snapshot()
    original.value = cloneSettings(snapshot)
    draft.value = cloneSettings(snapshot)
    loadState.value = 'ready'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
    loadState.value = 'error'
  }
}

async function saveSettings() {
  if (!draft.value || !original.value || !isDirty.value || saveState.value === 'saving') {
    return
  }

  saveState.value = 'saving'
  errorMessage.value = ''
  const pending = [...changes.value]

  try {
    for (const change of pending) {
      await settingsApi.set(change.category, change.key, change.value)
    }
    original.value = cloneSettings(draft.value)
    saveState.value = 'saved'
    if (savedTimer) window.clearTimeout(savedTimer)
    savedTimer = window.setTimeout(() => {
      if (!isDirty.value) saveState.value = 'idle'
    }, 2400)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
    saveState.value = 'error'
  }
}

function discardChanges() {
  if (!original.value || saveState.value === 'saving') return
  draft.value = cloneSettings(original.value)
  errorMessage.value = ''
  saveState.value = 'idle'
}

function setTheme(mode: ThemeMode) {
  if (draft.value) draft.value.appearance.theme_mode = mode
}

function jumpTo(section: string) {
  activeSection.value = section
  document.getElementById(section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const accentSwatches = ['#FF6B9D', '#2F7CF6', '#1F9D72', '#D97706', '#8B5CF6']
</script>

<template>
  <main class="app-shell" :style="accentStyle">
    <header class="topbar">
      <h1>设置</h1>
      <div class="topbar-status" aria-live="polite">
        <span v-if="loadState === 'ready'" class="status-dot" />
        <span v-if="saveState === 'saving'">正在保存</span>
        <span v-else-if="saveState === 'saved'">已保存</span>
        <span v-else-if="isDirty">有未保存更改</span>
        <span v-else-if="loadState === 'ready'">已连接</span>
      </div>
    </header>

    <div v-if="loadState === 'loading'" class="loading-view" aria-live="polite">
      <div v-for="index in 6" :key="index" class="skeleton-row">
        <span />
        <span />
      </div>
    </div>

    <div v-else-if="loadState === 'error'" class="error-view" role="alert">
      <strong>设置加载失败</strong>
      <p>{{ errorMessage }}</p>
      <button class="button primary" type="button" @click="loadSettings">重试</button>
    </div>

    <div v-else-if="draft" class="workspace">
      <nav class="section-nav" aria-label="设置分类">
        <button
          v-for="item in [
            { id: 'general', label: '通用' },
            { id: 'appearance', label: '外观' },
            { id: 'sidebar', label: '侧边栏' },
          ]"
          :key="item.id"
          type="button"
          :class="{ active: activeSection === item.id }"
          @click="jumpTo(item.id)"
        >
          {{ item.label }}
        </button>
      </nav>

      <div class="settings-content">
        <div v-if="saveState === 'error'" class="inline-error" role="alert">
          <span>{{ errorMessage }}</span>
          <button type="button" @click="saveSettings">重试保存</button>
        </div>

        <section id="general" class="settings-section">
          <div class="section-heading">
            <span>01</span>
            <h2>通用</h2>
          </div>

          <label class="setting-row toggle-row">
            <span>系统启动时运行</span>
            <input v-model="draft.general.run_on_startup" type="checkbox" class="toggle-input" />
          </label>
          <label class="setting-row toggle-row">
            <span>桌面通知</span>
            <input v-model="draft.general.enable_notifications" type="checkbox" class="toggle-input" />
          </label>
          <label class="setting-row numeric-row">
            <span>自动隐藏延迟</span>
            <span class="range-control">
              <input v-model.number="draft.general.auto_hide_delay" type="range" min="0" max="10000" step="100" />
              <input v-model.number="draft.general.auto_hide_delay" type="number" min="0" max="10000" step="100" />
              <span class="unit">ms</span>
            </span>
          </label>
          <label class="setting-row numeric-row">
            <span>触发区域宽度</span>
            <span class="range-control">
              <input v-model.number="draft.general.trigger_zone_width" type="range" min="1" max="50" />
              <input v-model.number="draft.general.trigger_zone_width" type="number" min="1" max="50" />
              <span class="unit">px</span>
            </span>
          </label>
        </section>

        <section id="appearance" class="settings-section">
          <div class="section-heading">
            <span>02</span>
            <h2>外观</h2>
          </div>

          <div class="setting-row">
            <span>主题</span>
            <div class="segmented-control" aria-label="主题">
              <button v-for="mode in [
                { value: 'light', label: '浅色' },
                { value: 'dark', label: '深色' },
                { value: 'system', label: '系统' },
              ] as const" :key="mode.value" type="button" :class="{ active: draft.appearance.theme_mode === mode.value }" @click="setTheme(mode.value)">
                {{ mode.label }}
              </button>
            </div>
          </div>

          <div class="setting-row color-row">
            <span>强调色</span>
            <div class="color-control">
              <button
                v-for="color in accentSwatches"
                :key="color"
                type="button"
                class="color-swatch"
                :class="{ active: draft.appearance.accent_color.toLowerCase() === color.toLowerCase() }"
                :style="{ backgroundColor: color }"
                :aria-label="color"
                @click="draft.appearance.accent_color = color"
              />
              <input v-model="draft.appearance.accent_color" type="color" aria-label="自定义强调色" />
            </div>
          </div>

          <label class="setting-row numeric-row">
            <span>字号</span>
            <span class="range-control">
              <input v-model.number="draft.appearance.font_size" type="range" min="8" max="32" />
              <input v-model.number="draft.appearance.font_size" type="number" min="8" max="32" />
              <span class="unit">px</span>
            </span>
          </label>
          <label class="setting-row numeric-row">
            <span>详情背景不透明度</span>
            <span class="range-control">
              <input v-model.number="draft.appearance.detail_bg_opacity" type="range" min="0.1" max="1" step="0.05" />
              <output>{{ Math.round(draft.appearance.detail_bg_opacity * 100) }}%</output>
            </span>
          </label>
        </section>

        <section id="sidebar" class="settings-section">
          <div class="section-heading">
            <span>03</span>
            <h2>侧边栏</h2>
          </div>

          <div class="setting-row">
            <span>位置</span>
            <div class="segmented-control two" aria-label="侧边栏位置">
              <button type="button" :class="{ active: draft.appearance.sidebar_position === 'left' }" @click="draft.appearance.sidebar_position = 'left'">左侧</button>
              <button type="button" :class="{ active: draft.appearance.sidebar_position === 'right' }" @click="draft.appearance.sidebar_position = 'right'">右侧</button>
            </div>
          </div>
          <label class="setting-row numeric-row">
            <span>展开宽度</span>
            <span class="range-control">
              <input v-model.number="draft.appearance.sidebar_width" type="range" min="320" max="1200" step="10" />
              <input v-model.number="draft.appearance.sidebar_width" type="number" min="320" max="1200" step="10" />
              <span class="unit">px</span>
            </span>
          </label>
          <label class="setting-row numeric-row">
            <span>收起宽度</span>
            <span class="range-control">
              <input v-model.number="draft.appearance.collapsed_width" type="range" min="32" max="96" />
              <input v-model.number="draft.appearance.collapsed_width" type="number" min="32" max="96" />
              <span class="unit">px</span>
            </span>
          </label>
          <label class="setting-row numeric-row">
            <span>图标尺寸</span>
            <span class="range-control">
              <input v-model.number="draft.appearance.icon_size" type="range" min="20" max="96" />
              <input v-model.number="draft.appearance.icon_size" type="number" min="20" max="96" />
              <span class="unit">px</span>
            </span>
          </label>
          <label class="setting-row numeric-row">
            <span>侧边栏不透明度</span>
            <span class="range-control">
              <input v-model.number="draft.appearance.sidebar_bg_opacity" type="range" min="0.1" max="1" step="0.05" />
              <output>{{ Math.round(draft.appearance.sidebar_bg_opacity * 100) }}%</output>
            </span>
          </label>
        </section>
      </div>

      <footer class="save-bar">
        <span>{{ changes.length }} 项更改</span>
        <div class="save-actions">
          <button class="button secondary" type="button" :disabled="!isDirty || saveState === 'saving'" @click="discardChanges">撤销</button>
          <button class="button primary" type="button" :disabled="!isDirty || saveState === 'saving'" @click="saveSettings">
            {{ saveState === 'saving' ? '保存中' : '保存更改' }}
          </button>
        </div>
      </footer>
    </div>
  </main>
</template>
