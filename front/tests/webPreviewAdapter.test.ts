import assert from 'node:assert/strict'
import test from 'node:test'

import type { SettingsSnapshot, SettingWriteResult } from '../src/types.ts'
import { browserPreviewAdapter } from '../src/services/webPreviewAdapter.ts'

test('preview adapter supports the real settings route contract', async () => {
  const write = await browserPreviewAdapter.invoke<SettingWriteResult>('core/settings/set', {
    category: 'appearance',
    key: 'sidebar_width',
    value: 680,
  })
  assert.equal(write.ok, true)
  assert.equal(write.data?.value, 680)

  const snapshot = await browserPreviewAdapter.invoke<SettingsSnapshot>(
    'core/settings/snapshot',
  )
  assert.equal(snapshot.ok, true)
  assert.equal(snapshot.data?.appearance.sidebar_width, 680)
})

test('preview adapter isolates snapshots and rejects unknown routes', async () => {
  const first = await browserPreviewAdapter.invoke<SettingsSnapshot>(
    'core/settings/snapshot',
  )
  if (!first.data) {
    throw new Error('Preview snapshot was not returned.')
  }
  first.data.appearance.sidebar_width = 999

  const second = await browserPreviewAdapter.invoke<SettingsSnapshot>(
    'core/settings/snapshot',
  )
  assert.equal(second.data?.appearance.sidebar_width, 680)

  const missing = await browserPreviewAdapter.invoke('plugins/example/missing')
  assert.deepEqual(missing, {
    ok: false,
    code: 'ROUTE_NOT_FOUND',
    message: '预览环境未实现此 API。',
  })
})
