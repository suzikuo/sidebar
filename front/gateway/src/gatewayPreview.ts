import type { PlatformAdapter } from '../../src/services/platformAdapter'
import type { ApiResult } from '../../src/types'
import type { GatewaySnapshot } from './types'

let preview: GatewaySnapshot = {
  running_count: 1,
  total_gateways: 2,
  gateways: [
    { id: 1, name: 'Local API', listen_host: '127.0.0.1', listen_port: 22343, enabled: true, auto_start: true, remarks: 'Main development gateway', running: true, error: '', routes_count: 2, requests_total: 1842, last_request_at: 0 },
    { id: 2, name: 'Preview', listen_host: '127.0.0.1', listen_port: 22480, enabled: true, auto_start: false, remarks: '', running: false, error: '', routes_count: 1, requests_total: 93, last_request_at: 0 },
  ],
  tunnels: [
    { id: 1, name: 'Public tunnel', cloudflared_path: 'cloudflared', gateway_id: 1, gateway_name: 'Local API', enabled: true, auto_start: true, remarks: '', has_token: true, running: true, pid: 12084, last_error: '', last_exit_code: null },
    { id: 2, name: 'Preview tunnel', cloudflared_path: 'cloudflared', gateway_id: 2, gateway_name: 'Preview', enabled: true, auto_start: false, remarks: '', has_token: true, running: false, pid: null, last_error: '', last_exit_code: 0 },
  ],
  services: [
    { id: 1, name: 'Password API', target_url: 'http://127.0.0.1:6694', enabled: true, remarks: '' },
    { id: 2, name: 'Assets', target_url: 'http://127.0.0.1:4173', enabled: true, remarks: '' },
    { id: 3, name: 'Preview API', target_url: 'http://127.0.0.1:8090', enabled: true, remarks: '' },
  ],
  routes: [
    { id: 1, gateway_id: 1, gateway_name: 'Local API', service_id: 1, service_name: 'Password API', target_url: 'http://127.0.0.1:6694', path_prefix: '/api', preserve_host: false, enabled: true },
    { id: 2, gateway_id: 1, gateway_name: 'Local API', service_id: 2, service_name: 'Assets', target_url: 'http://127.0.0.1:4173', path_prefix: '/assets', preserve_host: true, enabled: true },
    { id: 3, gateway_id: 2, gateway_name: 'Preview', service_id: 3, service_name: 'Preview API', target_url: 'http://127.0.0.1:8090', path_prefix: '/preview', preserve_host: false, enabled: true },
  ],
  logs: [
    { time: '18:42:16', level: 'info', message: 'GET /api/items -> 200 31ms' },
    { time: '18:41:58', level: 'info', message: 'GET /assets/app.css -> 200 8ms' },
    { time: '18:39:12', level: 'warning', message: 'No route for GET /favicon.ico on Local API' },
    { time: '18:37:03', level: 'info', message: 'Gateway Local API started on 127.0.0.1:22343' },
  ],
}

function clone(): GatewaySnapshot { return structuredClone(preview) }
function ok<T>(data: T): ApiResult<T> { return { ok: true, data } }

export const gatewayPreviewAdapter: PlatformAdapter = {
  async invoke<T>(route: string, payload: Record<string, unknown> = {}) {
    await Promise.resolve()
    if (route.endsWith('/action')) {
      const id = Number(payload.id)
      const running = String(payload.action).startsWith('start')
      if (String(payload.action).endsWith('gateway')) preview.gateways.find((item) => item.id === id)!.running = running
      if (String(payload.action).endsWith('tunnel')) preview.tunnels.find((item) => item.id === id)!.running = running
      if (payload.action === 'start_all' || payload.action === 'stop_all') preview.gateways.forEach((item) => { item.running = payload.action === 'start_all' })
      preview.running_count = preview.gateways.filter((item) => item.running).length
    }
    return ok(clone()) as ApiResult<T>
  },
}
