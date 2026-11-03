import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'
import * as vue from 'vue'

function deferred() {
	let resolve, reject
	const promise = new Promise((yes, no) => {
		resolve = yes
		reject = no
	})
	return { promise, resolve, reject }
}
function fixture() {
	const reads = [],
		writes = []
	const activeTeam = vue.ref('team-a'),
		resourceId = vue.ref('server-a')
	const exports = {}
	const source = readFileSync(
		new URL('../src/composables/useServerRescue.ts', import.meta.url),
		'utf8',
	)
	const compiled = typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText
	const dependencies = {
		vue,
		'frappe-ui': {
			frappeRequest: (args) => {
				const request = deferred()
				reads.push({ ...request, args })
				return request.promise
			},
			call: (method, args) => {
				const request = deferred()
				writes.push({ ...request, args, method })
				return request.promise
			},
		},
		'@/api/methods': {
			API: { getRescueState: 'read', setRescueMode: 'write' },
			methodV1: (name) => name,
		},
		'@/composables/useSession': { useSession: () => ({ activeTeam }) },
		'@/lib/feedback': { getErrorMessage: (error) => error.message },
	}
	runInNewContext(compiled, { exports, require: (name) => dependencies[name] })
	const scope = vue.effectScope()
	const rescue = scope.run(() => exports.useServerRescue(resourceId))
	return { reads, writes, resourceId, rescue, scope }
}
const normal = { is_rescue_mode_enabled: false, is_in_rescue_mode: false }
const flush = async () => {
	await Promise.resolve()
	await vue.nextTick()
}

test('late reads cannot replace the newly selected server', async () => {
	const f = fixture()
	f.resourceId.value = 'server-b'
	await vue.nextTick()
	f.reads[1].resolve(normal)
	await flush()
	f.reads[0].resolve({ is_rescue_mode_enabled: true, is_in_rescue_mode: true })
	await flush()
	assert.equal(f.rescue.state.value.is_rescue_mode_enabled, false)
	assert.equal(f.reads[1].args.params.resource_id, 'server-b')
	f.scope.stop()
})
test('unknown mode is preserved', async () => {
	const f = fixture()
	f.reads[0].resolve({ is_rescue_mode_enabled: null, is_in_rescue_mode: null })
	await flush()
	assert.equal(f.rescue.state.value.is_rescue_mode_enabled, null)
	f.scope.stop()
})
test('accepted selection survives a failed follow-up read', async () => {
	const f = fixture()
	f.reads[0].resolve(normal)
	await flush()
	const selection = f.rescue.select(true)
	f.writes[0].resolve(null)
	await flush()
	f.reads[1].reject(new Error('Status unavailable'))
	await selection
	assert.match(f.rescue.notice.value, /accepted/)
	assert.equal(f.rescue.error.value, 'Status unavailable')
	assert.equal(f.rescue.state.value, null)
	assert.equal(f.writes.length, 1)
	f.scope.stop()
})
test('uncertain writes and duplicate clicks do not repeat the mutation', async () => {
	const f = fixture()
	f.reads[0].resolve(normal)
	await flush()
	const selection = f.rescue.select(true)
	await f.rescue.select(true)
	f.writes[0].reject(new Error('Outcome unknown; refresh status'))
	await selection
	assert.equal(f.writes.length, 1)
	assert.equal(f.rescue.state.value, null)
	assert.equal(f.rescue.notice.value, '')
	assert.equal(f.rescue.saving.value, false)
	f.scope.stop()
})
test('leaving the control cancels follow-up work after a late write', async () => {
	const f = fixture()
	f.reads[0].resolve(normal)
	await flush()
	const selection = f.rescue.select(false)
	f.scope.stop()
	f.writes[0].resolve(null)
	await selection
	assert.equal(f.reads.length, 1)
})
