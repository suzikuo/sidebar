import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cloneSettings,
  collectSettingChanges,
  createPreviewSettings,
} from '../src/services/settingsModel.ts'

test('cloneSettings returns an isolated snapshot', () => {
  const original = createPreviewSettings()
  const cloned = cloneSettings(original)

  cloned.appearance.sidebar_width = 720
  cloned.plugins.enabled.push('bookmarks')

  assert.equal(original.appearance.sidebar_width, 500)
  assert.deepEqual(original.plugins.enabled, [])
})

test('collectSettingChanges reports only changed fields', () => {
  const original = createPreviewSettings()
  const draft = cloneSettings(original)
  draft.general.enable_notifications = false
  draft.appearance.accent_color = '#2F7CF6'

  assert.deepEqual(collectSettingChanges(original, draft), [
    { category: 'general', key: 'enable_notifications', value: false },
    { category: 'appearance', key: 'accent_color', value: '#2F7CF6' },
  ])
})

test('collectSettingChanges returns no work for identical snapshots', () => {
  const settings = createPreviewSettings()
  assert.deepEqual(collectSettingChanges(settings, cloneSettings(settings)), [])
})
