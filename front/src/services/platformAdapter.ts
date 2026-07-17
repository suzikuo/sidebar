import type { ApiResult } from '../types'
import { browserPreviewAdapter } from './webPreviewAdapter'
import { qtWebChannelAdapter } from './qtWebChannelAdapter'

export interface PlatformAdapter {
  invoke<T>(route: string, payload?: Record<string, unknown>): Promise<ApiResult<T>>
}

export const platformAdapter: PlatformAdapter =
  import.meta.env.MODE === 'desktop' ? qtWebChannelAdapter : browserPreviewAdapter
