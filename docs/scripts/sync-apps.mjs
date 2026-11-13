import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/** Copies the app guides of the one-click templates repository into content/apps. */
const docsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const target = path.join(docsDir, 'content/apps')
const checkout = path.join(docsDir, '.vitepress/cache/one-click-templates')
const repository = 'https://github.com/frappe/one-click-templates.git'

function getSource() {
	if (process.env.ONE_CLICK_DOCS) return path.resolve(process.env.ONE_CLICK_DOCS)

	rmSync(checkout, { recursive: true, force: true })
	execFileSync('git', ['clone', '--quiet', '--depth', '1', repository, checkout], { stdio: 'inherit' })
	return path.join(checkout, '_docs')
}

const source = getSource()
if (!existsSync(path.join(source, 'index.md'))) {
	throw new Error(`${source} has no index.md. Set ONE_CLICK_DOCS to the _docs folder of one-click-templates.`)
}

rmSync(target, { recursive: true, force: true })
cpSync(source, target, { recursive: true })
console.log(`Copied the app guides from ${source}.`)
