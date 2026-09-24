import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const vendor = join(root, '.vendor', 'fantastic-admin')
const overlay = join(root, 'overlays')
const lock = JSON.parse(readFileSync(join(root, 'upstream.lock.json'), 'utf8'))
const marker = join(vendor, '.agrm-upstream-revision')

function run(command, args, cwd = root) {
  execFileSync(command, args, { cwd, stdio: 'inherit' })
}

let current = ''
if (existsSync(marker)) {
  current = readFileSync(marker, 'utf8').trim()
}
if (current !== lock.commit) {
  rmSync(vendor, { recursive: true, force: true })
  mkdirSync(dirname(vendor), { recursive: true })
  run('git', ['clone', '--filter=blob:none', lock.repository, vendor])
  run('git', ['checkout', '--detach', lock.commit], vendor)
  writeFileSync(marker, lock.commit)
}
cpSync(overlay, vendor, { recursive: true, force: true })
console.log(`Fantastic Admin overlay ready at ${lock.commit}`)
