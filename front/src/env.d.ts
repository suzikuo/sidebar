/// <reference types="vite/client" />

interface QtSignal<TArgs extends unknown[]> {
  connect(callback: (...args: TArgs) => void): void
  disconnect?(callback: (...args: TArgs) => void): void
}

interface AgileApiObject {
  invoke(route: string, payloadJson: string, requestId: string): void
  response_ready: QtSignal<[requestId: string, resultJson: string]>
  event_ready: QtSignal<[eventName: string, payloadJson: string]>
}

interface QWebChannelInstance {
  objects: {
    agileApi?: AgileApiObject
  }
}

declare class QWebChannel {
  constructor(
    transport: unknown,
    callback: (channel: QWebChannelInstance) => void,
  )
}

interface Window {
  qt?: {
    webChannelTransport?: unknown
  }
  QWebChannel?: typeof QWebChannel
}
