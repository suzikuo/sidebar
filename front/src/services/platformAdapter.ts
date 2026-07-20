import type { ApiResult } from '../types'
import { browserPreviewAdapter } from './webPreviewAdapter'
import { qtWebChannelAdapter } from './qtWebChannelAdapter'

export interface PlatformAdapter {
  invoke<T>(route: string, payload?: Record<string, unknown>): Promise<ApiResult<T>>
  subscribe(eventName: string, callback: (payload: unknown) => void): () => void
}

export const platformAdapter: PlatformAdapter =
  ['desktop', 'gateway', 'control-center'].includes(import.meta.env.MODE) ? qtWebChannelAdapter : browserPreviewAdapter
