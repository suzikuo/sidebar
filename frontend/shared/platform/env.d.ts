/// <reference types="vite/client" />

interface QtSignal<TArgs extends unknown[]> {
  connect(callback: (...args: TArgs) => void): void
  disconnect?(callback: (...args: TArgs) => void): void
}
