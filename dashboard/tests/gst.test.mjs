import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/gst.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{ exports },
)
const { getMissingStateIgstRate } = exports

const profile = {
	team: 'acme',
	complete: true,
	gst_state_missing: true,
	igst_rate: 18,
}

test('a complete profile with no state shows the IGST it is charged', () => {
	assert.equal(getMissingStateIgstRate(profile, 'acme'), 18)
})

test('a profile loaded for another team shows nothing', () => {
	assert.equal(getMissingStateIgstRate(profile, 'other'), null)
})

test('a profile with its state set shows nothing, whatever the rate', () => {
	assert.equal(
		getMissingStateIgstRate({ ...profile, gst_state_missing: false }, 'acme'),
		null,
	)
})

test('a team charged no GST or with an incomplete profile shows nothing', () => {
	assert.equal(
		getMissingStateIgstRate({ ...profile, igst_rate: null }, 'acme'),
		null,
	)
	assert.equal(
		getMissingStateIgstRate({ ...profile, complete: false }, 'acme'),
		null,
	)
	assert.equal(getMissingStateIgstRate(null, 'acme'), null)
})
