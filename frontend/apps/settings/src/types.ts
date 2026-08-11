export type ThemeMode = 'light' | 'dark' | 'system'
export type SidebarPosition = 'left' | 'right'
export type FontWeight = 'light' | 'normal' | 'medium' | 'bold'
export type UiScale = 'auto' | '100' | '125' | '150' | '175' | '200'

export interface GeneralSettings {
  run_on_startup: boolean
  enable_notifications: boolean
  auto_hide_delay: number
  trigger_zone_width: number
}

export interface AppearanceSettings {
  theme_mode: ThemeMode
  ui_scale: UiScale
  sidebar_position: SidebarPosition
  sidebar_width: number
  collapsed_width: number
  icon_size: number
  font_family: string
  font_size: number
  font_weight: FontWeight
  accent_color: string
  peek_width: number
  sidebar_bg_opacity: number
  detail_bg_opacity: number
  sidebar_height_percent: number
  sidebar_hidden_height_percent: number
  sidebar_y_offset: number
  max_plugins_count: number
}

export interface SettingsSnapshot {
  general: GeneralSettings
  appearance: AppearanceSettings
  plugins: {
    enabled: string[]
    disabled: string[]
  }
  shortcuts: {
    toggle_sidebar: string
  }
}

export interface SettingWriteResult<T = unknown> {
  category: string
  key: string
  value: T
}
export type { ApiResult } from '../../../shared/platform/types'
