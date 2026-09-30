// Loopback-only server for the compiled production bundle used by Playwright.
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../dist/', import.meta.url))
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.ico': 'image/x-icon' }
createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname)
    const path = resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`)
    if (!path.startsWith(resolve(root) + sep)) {
      response.writeHead(403).end()
      return
    }
    const content = await readFile(path)
    response.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream', 'Cache-Control': 'no-store' }).end(content)
  }
  catch {
    response.writeHead(404).end('Not found')
  }
}).listen(4173, '127.0.0.1')
