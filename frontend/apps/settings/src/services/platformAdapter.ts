import type { PlatformAdapter } from '../../../../shared/platform/types'
import { qtNativeAdapter } from '../../../../shared/platform/qtNativeAdapter'
import { browserPreviewAdapter } from './webPreviewAdapter'

export const platformAdapter: PlatformAdapter =
  ['desktop', 'gateway', 'control-center'].includes(import.meta.env.MODE) ? qtNativeAdapter : browserPreviewAdapter
