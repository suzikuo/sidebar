export interface ApiResult<T> {
  ok: boolean
  data?: T
  code?: string
  message?: string
}

export interface PlatformAdapter {
  invoke<T>(route: string, payload?: Record<string, unknown>): Promise<ApiResult<T>>
  subscribe(eventName: string, callback: (payload: unknown) => void): () => void
}
