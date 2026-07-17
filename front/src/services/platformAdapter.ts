import type { ApiResult } from '../types'
import { browserPreviewAdapter } from './webPreviewAdapter'
import { qtWebChannelAdapter } from './qtWebChannelAdapter'

export interface PlatformAdapter {
  invoke<T>(route: string, payload?: Record<string, unknown>): Promise<ApiResult<T>>
}

export const platformAdapter: PlatformAdapter =
  ['desktop', 'gateway'].includes(import.meta.env.MODE) ? qtWebChannelAdapter : browserPreviewAdapter
