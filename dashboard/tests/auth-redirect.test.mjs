import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/authRedirect.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{
		exports,
		URL,
		URLSearchParams,
		window: { location: { origin: 'https://central.example.com' } },
		require: () => ({
			queryString: (value) => (typeof value === 'string' ? value : ''),
		}),
	},
)
const { signInDestination } = exports

test('sign-in returns to the mailbox callback with its query', () => {
	const callback =
		'/api/method/central.api.email_oauth.callback?state=s1&code=c1'
	assert.equal(signInDestination({ 'redirect-to': callback }), callback)
	assert.equal(
		signInDestination({
			'redirect-to': `https://central.example.com${callback}`,
		}),
		callback,
	)
})

test('sign-in refuses a foreign origin or a lookalike callback path', () => {
	for (const value of [
		'https://evil.example.com/api/method/central.api.email_oauth.callback?state=s1',
		'//evil.example.com/api/method/central.api.email_oauth.callback?state=s1',
		'/api/method/central.api.email_oauth.callback_evil?state=s1',
		'/api/method/central.api.email_oauth.callback',
		'/api/method/central.api.other?next=/api/method/central.api.email_oauth.callback?',
	]) {
		assert.equal(
			signInDestination({ 'redirect-to': value }),
			'/dashboard/servers',
			value,
		)
	}
})
