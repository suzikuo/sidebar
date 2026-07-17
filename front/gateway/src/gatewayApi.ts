import { platformAdapter } from '../../src/services/platformAdapter'
import { gatewayPreviewAdapter } from './gatewayPreview'
import type { GatewayAction, GatewayFormData, GatewayResource, GatewaySnapshot } from './types'

const routes = {
  snapshot: 'plugins/gateway_manager/snapshot',
  action: 'plugins/gateway_manager/action',
  save: 'plugins/gateway_manager/save',
  remove: 'plugins/gateway_manager/delete',
} as const
const adapter = import.meta.env.DEV ? gatewayPreviewAdapter : platformAdapter

async function invoke<T>(route: string, payload: Record<string, unknown> = {}): Promise<T> {
  const result = await adapter.invoke<T>(route, payload)
  if (!result.ok || result.data === undefined) throw new Error(result.message || result.code || '网关 API 调用失败。')
  return result.data
}

export const gatewayApi = {
  snapshot: () => invoke<GatewaySnapshot>(routes.snapshot),
  action: (action: GatewayAction, id?: number) => invoke<GatewaySnapshot>(routes.action, { action, id }),
  save: (resource: GatewayResource, data: GatewayFormData, id?: number) =>
    invoke<GatewaySnapshot>(routes.save, { resource, data, id }),
  remove: (resource: GatewayResource, id: number) =>
    invoke<GatewaySnapshot>(routes.remove, { resource, id }),
}
