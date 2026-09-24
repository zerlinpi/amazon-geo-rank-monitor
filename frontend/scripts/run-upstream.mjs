import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const vendor = join(root, '.vendor', 'fantastic-admin')
const mode = process.argv[2] ?? 'build'
const pnpm = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'

execFileSync(process.execPath, [join(here, 'sync-upstream.mjs')], { stdio: 'inherit' })
execFileSync('corepack', ['prepare', 'pnpm@11.24.0', '--activate'], { stdio: 'inherit' })

if (mode === 'dev') {
  execFileSync(pnpm, ['--filter', '@fantastic-admin/core-element-plus', 'dev'], {
    cwd: vendor,
    stdio: 'inherit',
    env: process.env,
  })
}
else {
  execFileSync(pnpm, ['install', '--frozen-lockfile'], { cwd: vendor, stdio: 'inherit' })
  execFileSync(pnpm, ['--filter', '@fantastic-admin/core-element-plus', 'build'], {
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
