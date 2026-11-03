import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'
import * as vue from 'vue'

function createFixture(openWindow, rejectRequest = false) {
	const errors = []
	const requests = []
	const window = { open: openWindow, location: { href: '' } }
	const exports = {}
	const source = readFileSync(
		new URL('../src/composables/useServers.ts', import.meta.url),
		'utf8',
	)
	const compiled = typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText
	const dependencies = {
		vue,
		'frappe-ui': { useCall: (options) => ({ options }) },
		'@/api/methods': {
			API: { openConsole: 'console' },
			method: (value) => value,
		},
		'@/assets/signing-in.html?url&no-inline': '/assets/signing-in.html',
		'@/composables/useBusyRunner': { useBusyRunner: () => ({}) },
		'@/composables/useSession': {
			useSession: () => ({ activeTeam: vue.ref('team') }),
		},
		'@/lib/feedback': { reportError: (error) => errors.push(error) },
		'@/lib/frappeCall': {
			submitOrThrow: async (call, args) => {
				requests.push(args)
				if (rejectRequest) throw new Error('region unavailable')
				call.data = { url: 'https://atlas.example.test/console' }
			},
		},
	}
	runInNewContext(compiled, {
		exports,
		window,
		require: (name) => dependencies[name],
	})
	return { servers: exports.useServers(), errors, requests, window }
}

const server = { resource_id: 'test-vm' }

test('console opens a served loading page in a reusable tab before requesting a session', async () => {
	const calls = []
	const tab = { location: { href: '' } }
	const context = createFixture((...args) => {
		assert.equal(context.requests.length, 0)
		calls.push(args)
		return tab
	})
	const pending = context.servers.openConsole(server, 'ssh')
	assert.deepEqual(calls, [['/assets/signing-in.html', 'console-test-vm']])
	await pending
	assert.equal(tab.location.href, 'https://atlas.example.test/console')
	assert.equal(context.requests[0].mode, 'ssh')
	assert.equal(context.servers.opening.value, '')
})

test('window creation failure is reported and releases the busy state for retry', async () => {
	let failToOpen = true
	const context = createFixture(() => {
		if (failToOpen) throw new Error('window refused')
		return null
	})
	await context.servers.openConsole(server, 'ssh')
	assert.equal(context.errors[0].message, 'window refused')
	assert.equal(context.requests.length, 0)
	assert.equal(context.servers.opening.value, '')
	failToOpen = false
	await context.servers.openConsole(server, 'tty')
	assert.equal(context.requests.length, 1)
	assert.equal(
		context.window.location.href,
		'https://atlas.example.test/console',
	)
})

test('failed session request closes the loading tab and releases busy state', async () => {
	let closed = false
	const context = createFixture(
		() => ({
			close: () => {
				closed = true
			},
		}),
		true,
	)
	await context.servers.openConsole(server, 'tty')
	assert.equal(closed, true)
	assert.equal(context.errors[0].message, 'region unavailable')
	assert.equal(context.servers.opening.value, '')
})
