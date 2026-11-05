import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

function compile(path, dependencies, globals = {}) {
	const source = readFileSync(new URL(path, import.meta.url), 'utf8')
	const compiled = typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText
	const exports = {}
	runInNewContext(compiled, {
		exports,
		require: (name) => dependencies[name],
		URL,
		URLSearchParams,
		...globals,
	})
	return exports
}

const queryString = (value) => (typeof value === 'string' ? value : '')
const location = { origin: 'https://cloud.example.test' }
const authRedirect = compile(
	'../src/lib/authRedirect.ts',
	{ '@/lib/auth': { queryString } },
	{ window: { location } },
)

function signIn(query, { teamsFail = false } = {}) {
	const calls = []
	const window = {
		location: { ...location, replace: (path) => calls.push(['load', path]) },
	}
	const { useEmailSignIn } = compile(
		'../src/composables/useEmailSignIn.ts',
		{
			'vue-router': {
				useRouter: () => ({ replace: async (to) => calls.push(['route', to]) }),
			},
			'@/api/methods': { API: {} },
			'@/composables/useAuth': {
				useAuth: () => ({
					enterSession: (...args) => calls.push(['session', ...args]),
				}),
			},
			'@/composables/useProduct': {
				useProduct: () => ({ productKey: { value: '' } }),
			},
			'@/composables/useSession': {
				useSession: () => ({
					reload: async () => {
						calls.push(['teams'])
						if (teamsFail) throw new Error('my_teams failed')
					},
				}),
			},
			'@/lib/auth': { methodUrl: (path) => path, postFrappe: async () => ({}) },
			'@/lib/authRedirect': authRedirect,
		},
		{ window },
	)
	return useEmailSignIn()
		.enterConsole({ user: 'ada@example.test', csrf_token: 'token' }, query)
		.then(() => JSON.parse(JSON.stringify(calls)))
}

test('a product signup enters its session and moves on without a page load', async () => {
	const calls = await signIn({ product: 'raven' })

	assert.deepEqual(calls, [
		['session', 'ada@example.test', 'token'],
		['teams'],
		['route', { path: '/onboarding/site', query: { product: 'raven' } }],
	])
})

test('a failed in-place start falls back to a full load of the same step', async () => {
	const calls = await signIn({ product: 'raven' }, { teamsFail: true })

	assert.deepEqual(calls.at(-1), [
		'load',
		'/dashboard/onboarding/site?product=raven',
	])
	assert.ok(!calls.some(([kind]) => kind === 'route'))
})

test('any other sign-in boots the console with a full load', async () => {
	assert.deepEqual(await signIn({}), [['load', '/dashboard/servers']])
	assert.deepEqual(
		await signIn({ product: 'raven', 'redirect-to': '/dashboard/billing' }),
		[['load', '/dashboard/billing']],
	)
})
