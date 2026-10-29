import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

function load(path, dependencies = {}) {
	const source = readFileSync(new URL(path, import.meta.url), 'utf8')
	const exports = {}
	runInNewContext(
		typescript.transpileModule(source, {
			compilerOptions: { module: typescript.ModuleKind.CommonJS },
		}).outputText,
		{ exports, require: (name) => dependencies[name] },
	)
	return exports
}

const supportContexts = []
const menu = load('../src/lib/serverMenu.ts', {
	'@/composables/useSupport': {
		useSupport: () => ({
			getContactSupportOption: (context) => {
				supportContexts.push(context)
				return { label: 'Contact support' }
			},
		}),
	},
	'@/lib/capabilities': { ACCESS_LOCKED_REASON: 'Not in the free trial.' },
	'@/lib/clipboard': { copyToClipboard: async () => true },
	'@/lib/feedback': { reportError: () => {}, successToast: () => {} },
	'@/lib/status': load('../src/lib/status.ts'),
})

const allowed = {
	open: false,
	power: false,
	resize: false,
	snapshot: false,
	terminate: false,
	console: true,
}

function getConsoleRow(status) {
	const verbs = []
	const server = { resource_id: 'vm-1', status, pending_action: null }
	const row = menu
		.getServerMenuGroups(server, allowed, (verb) => verbs.push(verb), {
			isOnServerPage: true,
		})
		.flat()
		.find((option) => option.label === 'Web console')
	return { row, verbs }
}

test('web console offers SSH and TTY in a submenu', () => {
	const { row, verbs } = getConsoleRow('Running')

	assert.equal(row.disabled, false)
	assert.deepEqual(
		[...row.submenu].map((item) => item.label),
		['SSH session', 'Serial console (TTY)'],
	)

	for (const item of row.submenu) item.onClick()
	assert.deepEqual(verbs, ['ssh-console', 'tty-console'])
})

test('a flat list names each console mode and keeps the parent disabled state', () => {
	const { row } = getConsoleRow('Stopped')
	const items = menu.withSubmenuItems(row)

	assert.deepEqual(
		[...items].map((item) => [item.label, item.disabled]),
		[
			['Web console: SSH session', true],
			['Web console: Serial console (TTY)', true],
		],
	)
})

test('Contact support sits beside Copy server ID and names the server and its site', () => {
	supportContexts.length = 0
	const server = { resource_id: 'vm-1', title: 'acme', status: 'Running' }

	const labels = menu
		.getServerMenuGroups(server, allowed, () => {}, { site: 'acme.test' })
		.at(-1)
		.map((option) => option.label)

	assert.deepEqual([...labels], ['Copy server ID', 'Contact support'])
	assert.deepEqual(
		{ ...supportContexts[0] },
		{ Server: 'acme (vm-1)', Site: 'acme.test' },
	)
})

test('a locked web console is one disabled row with the reason and no submenu', () => {
	const server = {
		resource_id: 'vm-1',
		status: 'Running',
		pending_action: null,
	}
	const locked = { ...allowed, isAccessLocked: true }

	const row = menu
		.getServerMenuGroups(server, locked, () => {}, { isOnServerPage: true })
		.flat()
		.find((option) => option.label === 'Web console')

	assert.equal(row.disabled, true)
	assert.equal('submenu' in row, false)
	assert.equal(row.description, 'Not in the free trial.')
})
