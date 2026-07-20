import assert from 'node:assert/strict'
import test from 'node:test'

import { collectSettingChanges, movePluginOrder } from '../control-center/src/model.ts'
import type { SettingsSchema, SettingsSnapshot } from '../control-center/src/types.ts'

const schema: SettingsSchema = {
  appearance: {
    title: '外观',
    description: '',
    items: {
      theme_mode: {
        label: '主题',
        description: '',
        control: 'segmented',
        default: 'dark',
      },
      sidebar_width: {
        label: '宽度',
        description: '',
        control: 'range',
        default: 500,
      },
    },
  },
}

test('control center settings diff follows the backend schema', () => {
  const original: SettingsSnapshot = {
    appearance: { theme_mode: 'dark', sidebar_width: 500, legacy: true },
  }
  const draft: SettingsSnapshot = {
    appearance: { theme_mode: 'light', sidebar_width: 500, legacy: false },
  }

  assert.deepEqual(collectSettingChanges(schema, original, draft), [
    { category: 'appearance', key: 'theme_mode', value: 'light' },
  ])
})

test('plugin ordering moves one installed plugin without mutating input', () => {
  const order = ['first', 'second', 'third']
  assert.deepEqual(movePluginOrder(order, 'second', -1), ['second', 'first', 'third'])
  assert.deepEqual(order, ['first', 'second', 'third'])
  assert.equal(movePluginOrder(order, 'first', -1), null)
  assert.equal(movePluginOrder(order, 'missing', 1), null)
})
