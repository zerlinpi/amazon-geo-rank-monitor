import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const vendor = join(root, '.vendor', 'fantastic-admin')
const mode = process.argv[2] ?? 'build'
execFileSync(process.execPath, [join(here, 'sync-upstream.mjs')], { stdio: 'inherit' })
execFileSync('corepack', ['prepare', 'pnpm@11.24.0', '--activate'], { stdio: 'inherit' })

function runPnpm(args, options = {}) {
  execFileSync('corepack', ['pnpm', ...args], options)
}

if (mode === 'dev') {
  runPnpm(['--filter', '@fantastic-admin/core-element-plus', 'dev'], {
    cwd: vendor,
    stdio: 'inherit',
    env: process.env,
  })
}
else {
  runPnpm(['install', '--frozen-lockfile'], { cwd: vendor, stdio: 'inherit' })
  runPnpm(['--filter', '@fantastic-admin/core-element-plus', 'build'], {
    cwd: vendor,
    stdio: 'inherit',
    env: process.env,
  })
  const source = join(vendor, 'apps', 'core-element-plus', 'dist')
  const target = join(root, 'dist')
  rmSync(target, { recursive: true, force: true })
  mkdirSync(target, { recursive: true })
  cpSync(source, target, { recursive: true })
}
