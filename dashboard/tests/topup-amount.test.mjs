import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/topupAmount.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{ exports },
)
const { parseTopupAmount } = exports

test('a link amount prefills the top-up', () => {
	assert.equal(parseTopupAmount('40000'), 40000)
	assert.equal(parseTopupAmount('1'), 1)
	assert.equal(parseTopupAmount('2500.50'), 2500.5)
	assert.equal(parseTopupAmount(['40000']), 40000)
})

test('anything that is not a positive amount in range is ignored', () => {
	for (const value of [
		undefined,
		null,
		'',
		'0',
		'0.5',
		'-100',
		'abc',
		'1e5',
		'Infinity',
		'40000;drop',
		'100000000',
		[],
	])
		assert.equal(parseTopupAmount(value), null, String(value))
})
