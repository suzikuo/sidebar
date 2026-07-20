import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const buildTargets = new Set(['desktop', 'gateway', 'control-center', 'web'])

function desktopFileProtocolPlugin(target: string): Plugin {
  return {
    name: 'desktop-file-protocol-html',
    transformIndexHtml(html) {
      if (target === 'web') return html
      return html
        .replace(
          /<script type="module" crossorigin src="([^"]+)"><\/script>/g,
          '<script type="module" src="$1"></script>',
        )
        .replace(
          /<link rel="stylesheet" crossorigin href="([^"]+)">/g,
          '<link rel="stylesheet" href="$1">',
        )
    },
  }
}

function localDevCspPlugin(command: string): Plugin {
  return {
    name: 'local-dev-csp',
    transformIndexHtml(html) {
      if (command !== 'serve') return html
      return html
        .replace(
          "connect-src 'none'",
          "connect-src 'self' ws://127.0.0.1:* http://127.0.0.1:*",
        )
        .replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
    },
  }
}

export default defineConfig(({ command, mode }) => {
  const target = buildTargets.has(mode) ? mode : 'desktop'
  const gatewayBuild = target === 'gateway'
  const controlCenterBuild = mode === 'control-center' || mode === 'control-center-preview'

  return {
    root: gatewayBuild
      ? fileURLToPath(new URL('./gateway', import.meta.url))
      : controlCenterBuild
        ? fileURLToPath(new URL('./control-center', import.meta.url))
        : undefined,
    plugins: [vue(), desktopFileProtocolPlugin(target), localDevCspPlugin(command)],
    base: './',
    build: {
      outDir: gatewayBuild
        ? fileURLToPath(new URL('../plugins/gateway_manager/web', import.meta.url))
        : controlCenterBuild
          ? fileURLToPath(new URL('../ui/control_center/web', import.meta.url))
          : `dist/${target}`,
      emptyOutDir: true,
      target: 'es2020',
      cssTarget: 'chrome90',
    },
  }
})
