import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const require = createRequire(import.meta.url)
const vue = require('vue')
const load = (path, dependencies) => {
	const exports = {}
	const source = readFileSync(new URL(path, import.meta.url), 'utf8')
	runInNewContext(
		typescript.transpileModule(source, {
			compilerOptions: { module: typescript.ModuleKind.CommonJS },
		}).outputText,
		{ exports, require: (name) => dependencies[name] },
	)
	return exports
}

function startOverview() {
	const calls = []
	const feedback = load('../src/lib/feedback.ts', {
		vue,
		'frappe-ui': { toast: {} },
	})
	const { useServerOverview } = load(
		'../src/composables/useServerOverview.ts',
		{
			vue,
			'frappe-ui': {
				useCall: () => {
					const call = vue.reactive({
						data: null,
						error: null,
						loading: false,
						submit() {},
					})
					calls.push(call)
					return call
				},
			},
			'@/api/methods': { API: {}, method: (value) => value },
			'@/composables/useSession': {
				useSession: () => ({ activeTeam: vue.ref('') }),
			},
			'@/lib/feedback': feedback,
			'@/lib/serverMetrics': { LONGEST_METRICS_SECONDS: 30 * 86400 },
			'@/lib/translate': { __: (text) => text },
		},
	)
	const overview = useServerOverview(
		vue.ref('vm-1'),
		vue.ref({ period: '24h' }),
	)
	return { overview, metricsCall: calls[1] }
}

test('a usage request that a newer zoom aborted is not a load failure', () => {
	const { overview, metricsCall } = startOverview()

	for (const error of [
		new DOMException('signal is aborted without reason', 'AbortError'),
		{ message: 'signal is aborted without reason' },
	]) {
		metricsCall.error = error
		assert.equal(overview.metricsError.value, '')
	}

	metricsCall.error = { message: 'Atlas is unreachable' }
	assert.equal(overview.metricsError.value, 'Atlas is unreachable')
})
