import type { ApiResult, PlatformAdapter } from './types'

const REQUEST_TIMEOUT_MS = 15_000
const FRAGMENT_PREFIX = 'agile-tiles-bridge:'
const TITLE_PREFIX = '__AGILE_TILES_BRIDGE__:'

interface PendingRequest {
  resolve: (result: ApiResult<unknown>) => void
  timeoutId: ReturnType<typeof window.setTimeout>
}

interface BridgeRequest {
  type: 'invoke'
  id: string
  route: string
  payload: Record<string, unknown>
}

interface BridgeResponse {
  type: 'response'
  id: string
  result: ApiResult<unknown>
}

interface BridgeEvent {
  type: 'event'
  event: string
  payload: unknown
}

declare global {
  interface Window {
    __agileTilesBridgeTakeRequests?: () => string
    __agileTilesBridgeDeliver?: (message: BridgeResponse | BridgeEvent) => void
  }
}

let requestSequence = 0
let notificationScheduled = false
const queuedRequests = new Map<string, BridgeRequest>()
const pendingRequests = new Map<string, PendingRequest>()
const eventSubscribers = new Map<string, Set<(payload: unknown) => void>>()

function fail<T>(code: string, message: string): ApiResult<T> {
  return { ok: false, code, message }
}

function requestId(): string {
  requestSequence += 1
  return `request-${Date.now().toString(36)}-${requestSequence.toString(36)}`
}

function handleMessage(message: BridgeResponse | BridgeEvent): void {
  if (!message || typeof message !== 'object') return
  if (message.type === 'event') {
    const subscribers = eventSubscribers.get(message.event)
    if (!subscribers?.size) return
    for (const subscriber of subscribers) subscriber(message.payload)
    return
  }

  const pending = pendingRequests.get(message.id)
  if (!pending) return
  window.clearTimeout(pending.timeoutId)
  pendingRequests.delete(message.id)
  if (!message.result || typeof message.result !== 'object' || typeof message.result.ok !== 'boolean') {
    pending.resolve(fail('INVALID_RESPONSE', '桌面端返回了无效响应。'))
    return
  }
  pending.resolve(message.result)
}

window.__agileTilesBridgeTakeRequests = () => {
  const requests = Array.from(queuedRequests.values())
  queuedRequests.clear()
  return JSON.stringify(requests)
}
window.__agileTilesBridgeDeliver = handleMessage

function notifyHost(id: string): void {
  if (notificationScheduled) return
  if (document.readyState !== 'complete') {
    notificationScheduled = true
    window.addEventListener(
      'load',
      () => {
        notificationScheduled = false
        notifyHost(id)
      },
      { once: true },
    )
    return
  }
  notificationScheduled = true
  window.setTimeout(() => {
    document.title = `${TITLE_PREFIX}${id}`
    window.location.hash = `${FRAGMENT_PREFIX}${id}`
    notificationScheduled = false
  }, 0)
}

export const qtNativeAdapter: PlatformAdapter = {
  async invoke<T>(route: string, payload: Record<string, unknown> = {}) {
    const id = requestId()
    return await new Promise<ApiResult<T>>((resolve) => {
      const timeoutId = window.setTimeout(() => {
        queuedRequests.delete(id)
        pendingRequests.delete(id)
        resolve(fail('REQUEST_TIMEOUT', '桌面端 API 请求超时。'))
      }, REQUEST_TIMEOUT_MS)
      pendingRequests.set(id, {
        resolve: resolve as (result: ApiResult<unknown>) => void,
        timeoutId,
      })
      queuedRequests.set(id, { type: 'invoke', id, route, payload })
      notifyHost(id)
    })
  },
  subscribe(eventName, callback) {
    const subscribers = eventSubscribers.get(eventName) ?? new Set()
    subscribers.add(callback)
    eventSubscribers.set(eventName, subscribers)
    return () => {
      subscribers.delete(callback)
      if (!subscribers.size) eventSubscribers.delete(eventName)
    }
  },
}
