import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const buildTargets = new Set(['desktop', 'gateway', 'control-center', 'web'])

const appRoots = {
  settings: fileURLToPath(new URL('./apps/settings', import.meta.url)),
  gateway: fileURLToPath(new URL('./apps/gateway', import.meta.url)),
  controlCenter: fileURLToPath(new URL('./apps/control-center', import.meta.url)),
}

function asText(source: string | Uint8Array): string {
  return typeof source === 'string' ? source : new TextDecoder().decode(source)
}

function desktopSingleFilePlugin(target: string): Plugin {
  return {
    name: 'desktop-single-file-html',
    enforce: 'post',
    generateBundle(_options, bundle) {
      if (target === 'web') return
      const htmlAsset = bundle['index.html']
      if (!htmlAsset || htmlAsset.type !== 'asset') {
        throw new Error('Desktop build did not produce index.html.')
      }

      let html = asText(htmlAsset.source)
      const scripts: string[] = []
      const styles: string[] = []

      html = html.replace(
        /<script\s+type="module"(?:\s+crossorigin)?\s+src="\.\/([^"]+)"><\/script>/g,
        (_tag, fileName: string) => {
          const chunk = bundle[fileName]
          if (!chunk || chunk.type !== 'chunk') {
            throw new Error(`Desktop script asset is missing: ${fileName}`)
          }
          const source = chunk.code.replace(/<\/script/gi, '<\\/script')
          scripts.push(source)
          delete bundle[fileName]
          return ''
        },
      )
      html = html.replace(
        /<link\s+rel="stylesheet"(?:\s+crossorigin)?\s+href="\.\/([^"]+)">/g,
        (_tag, fileName: string) => {
          const asset = bundle[fileName]
          if (!asset || asset.type !== 'asset') {
            throw new Error(`Desktop stylesheet asset is missing: ${fileName}`)
          }
          const source = asText(asset.source).replace(/<\/style/gi, '<\\/style')
          styles.push(source)
          delete bundle[fileName]
          return ''
        },
      )

      if (!scripts.length) throw new Error('Desktop build contains no application script.')
      if (/<(?:script|link)\b[^>]+(?:src|href)="\.\//i.test(html)) {
        throw new Error('Desktop build contains unresolved local script or style assets.')
      }

      if (!html.includes("script-src 'self' 'unsafe-inline'")) {
        html = html.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
      }
      if (!html.includes("style-src 'self' 'unsafe-inline'")) {
        html = html.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
      }
      if (styles.length) {
        html = html.replace(
          '</head>',
          () => `    <style>${styles.join('\n')}</style>\n  </head>`,
        )
      }
      html = html.replace(
        '</body>',
        () => `    <script>${scripts.join('\n')}</script>\n  </body>`,
      )
      htmlAsset.source = html
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
      ? appRoots.gateway
      : controlCenterBuild
        ? appRoots.controlCenter
        : appRoots.settings,
    plugins: [vue(), desktopSingleFilePlugin(target), localDevCspPlugin(command)],
    base: './',
    build: {
      outDir: gatewayBuild
        ? fileURLToPath(new URL('../plugins/gateway_manager/web', import.meta.url))
        : controlCenterBuild
          ? fileURLToPath(new URL('../resources/web/control-center', import.meta.url))
          : fileURLToPath(new URL(`./dist/${target}`, import.meta.url)),
      emptyOutDir: true,
      target: 'es2020',
      cssTarget: 'chrome90',
    },
  }
})
