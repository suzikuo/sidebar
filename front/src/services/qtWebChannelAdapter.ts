import type { ApiResult } from '../types'
import type { PlatformAdapter } from './platformAdapter'

const CHANNEL_TIMEOUT_MS = 15_000
const REQUEST_TIMEOUT_MS = 15_000

interface PendingRequest {
  resolve: (result: ApiResult<unknown>) => void
  timeoutId: ReturnType<typeof window.setTimeout>
}

let requestSequence = 0
let apiPromise: Promise<AgileApiObject> | null = null
const pendingRequests = new Map<string, PendingRequest>()
const eventSubscribers = new Map<string, Set<(payload: unknown) => void>>()

function fail<T>(code: string, message: string): ApiResult<T> {
  return { ok: false, code, message }
}

function requestId(): string {
  requestSequence += 1
  return `settings-${Date.now().toString(36)}-${requestSequence.toString(36)}`
}

function handleResponse(id: string, resultJson: string): void {
  const pending = pendingRequests.get(id)
  if (!pending) return

  window.clearTimeout(pending.timeoutId)
  pendingRequests.delete(id)

  try {
    const parsed = JSON.parse(resultJson) as ApiResult<unknown>
    if (!parsed || typeof parsed !== 'object' || typeof parsed.ok !== 'boolean') {
      pending.resolve(fail('INVALID_RESPONSE', '桌面端返回了无效响应。'))
      return
    }
    pending.resolve(parsed)
  } catch {
    pending.resolve(fail('INVALID_RESPONSE', '桌面端返回了无法解析的响应。'))
  }
}

function handleEvent(eventName: string, payloadJson: string): void {
  const subscribers = eventSubscribers.get(eventName)
  if (!subscribers?.size) return
  let payload: unknown = {}
  try {
    payload = JSON.parse(payloadJson)
  } catch {
    return
  }
  for (const subscriber of subscribers) subscriber(payload)
}

async function resolveApi(): Promise<AgileApiObject> {
  if (apiPromise) return apiPromise

  apiPromise = new Promise<AgileApiObject>((resolve, reject) => {
    const transport = window.qt?.webChannelTransport
    const WebChannel = window.QWebChannel
    if (!transport || !WebChannel) {
      reject(new Error('QWebChannel 未注入。请通过 Agile Tiles 桌面端打开此页面。'))
      return
    }

    const timeoutId = window.setTimeout(() => {
      apiPromise = null
      reject(new Error('连接桌面端 API 超时。'))
    }, CHANNEL_TIMEOUT_MS)

    new WebChannel(transport, (channel) => {
      const api = channel.objects.agileApi
      if (!api) {
        window.clearTimeout(timeoutId)
        apiPromise = null
        reject(new Error('桌面端未注册 agileApi。'))
        return
      }

      api.response_ready.connect(handleResponse)
      api.event_ready.connect(handleEvent)
      window.clearTimeout(timeoutId)
      resolve(api)
    })
  })

  return apiPromise
}

export const qtWebChannelAdapter: PlatformAdapter = {
  async invoke<T>(route: string, payload: Record<string, unknown> = {}) {
    try {
      const api = await resolveApi()
      const id = requestId()

      return await new Promise<ApiResult<T>>((resolve) => {
        const timeoutId = window.setTimeout(() => {
          pendingRequests.delete(id)
          resolve(fail('REQUEST_TIMEOUT', '桌面端 API 请求超时。'))
        }, REQUEST_TIMEOUT_MS)

        pendingRequests.set(id, {
          resolve: resolve as (result: ApiResult<unknown>) => void,
          timeoutId,
        })

        try {
          api.invoke(route, JSON.stringify(payload), id)
        } catch (error) {
          window.clearTimeout(timeoutId)
          pendingRequests.delete(id)
          resolve(
            fail(
              'BRIDGE_ERROR',
              error instanceof Error ? error.message : String(error),
            ),
          )
        }
      })
    } catch (error) {
      return fail(
        'BRIDGE_NOT_READY',
        error instanceof Error ? error.message : String(error),
      )
    }
  },
  subscribe(eventName, callback) {
    const subscribers = eventSubscribers.get(eventName) ?? new Set()
    subscribers.add(callback)
    eventSubscribers.set(eventName, subscribers)
    void resolveApi().catch(() => undefined)
    return () => {
      subscribers.delete(callback)
      if (!subscribers.size) eventSubscribers.delete(eventName)
    }
  },
}
