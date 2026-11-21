import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const transpile = (source) =>
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText

const escapeModule = { exports: {} }
runInNewContext(transpile(read('../src/components/search/utils.ts')), {
	exports: escapeModule.exports,
	require: () => ({}),
})

const exports = {}
const modules = {
	'@/assets/signing-in.html?raw': {
		__esModule: true,
		default: read('../src/assets/signing-in.html'),
	},
	'@/components/search/utils': escapeModule.exports,
	'@/lib/translate': { __: (text) => text },
}
runInNewContext(transpile(read('../src/lib/loadingTab.ts')), {
	exports,
	require: (name) => modules[name],
})
const { getLoadingPageHtml } = exports

test('the loading page escapes a server name so it cannot run script', () => {
	const html = getLoadingPageHtml({
		title: 'Opening <img src=x onerror=alert(1)>',
		message: 'Filing the flight plan…',
		back: 'Back to dashboard',
	})

	assert.ok(!html.includes('<img src=x'))
	assert.ok(html.includes('Opening &lt;img src=x onerror=alert(1)&gt;'))
	assert.ok(!html.includes('{{'))
})
