export type GatewayResource = 'service' | 'gateway' | 'route' | 'tunnel'
export type GatewayTab = 'overview' | 'tunnels' | 'services' | 'gateways' | 'routes' | 'status'
export type GatewayAction =
  | 'start_all'
  | 'stop_all'
  | 'start_all_tunnels'
  | 'stop_all_tunnels'
  | 'start_gateway'
  | 'stop_gateway'
  | 'start_tunnel'
  | 'stop_tunnel'

export interface ServiceRecord {
  id: number
  name: string
  target_url: string
  enabled: boolean
  remarks: string
}

export interface GatewayRecord {
  id: number
  name: string
  listen_host: string
  listen_port: number
  enabled: boolean
  auto_start: boolean
  remarks: string
  running: boolean
  error: string
  routes_count: number
  requests_total: number
  last_request_at: number
}

export interface RouteRecord {
  id: number
  gateway_id: number
  gateway_name: string
  service_id: number
  service_name: string
  target_url: string
  path_prefix: string
  preserve_host: boolean
  enabled: boolean
}

export interface TunnelRecord {
  id: number
  name: string
  cloudflared_path: string
  gateway_id: number | null
  gateway_name: string
  enabled: boolean
  auto_start: boolean
  remarks: string
  has_token: boolean
  running: boolean
  pid: number | null
  last_error: string
  last_exit_code: number | null
}

export interface GatewayLog {
  time: string
  level: 'info' | 'warning' | 'error' | string
  message: string
}

export interface GatewaySnapshot {
  running_count: number
  total_gateways: number
  gateways: GatewayRecord[]
  tunnels: TunnelRecord[]
  services: ServiceRecord[]
  routes: RouteRecord[]
  logs: GatewayLog[]
}

export type GatewayItem = ServiceRecord | GatewayRecord | RouteRecord | TunnelRecord
export type GatewayFormData = Record<string, string | number | boolean | null | undefined>
