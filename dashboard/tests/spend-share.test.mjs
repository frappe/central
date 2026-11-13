import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/spendShare.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{ exports },
)
const { walletCoverPercent, spendLimitRatio } = exports

test('the wallet covers what the card or UPI is not left to pay', () => {
	// A ₹11,800 bill; ₹10,000 of top-ups with ₹1,800 GST paid on them leave nothing.
	assert.equal(walletCoverPercent(11800, 0), 100)
	assert.equal(walletCoverPercent(11800, 1800), 84)
	assert.equal(walletCoverPercent(11800, 11800), 0)
})

test('a shortfall outside the bill is clamped', () => {
	assert.equal(walletCoverPercent(1000, 5000), 0)
	assert.equal(walletCoverPercent(1000, -5), 100)
	assert.equal(walletCoverPercent(0, 0), 100)
})

test('the spend bar compares spend before tax with the limit before tax', () => {
	// ₹10,000 before tax against a ₹10,000 limit is full, though ₹11,800 is charged.
	assert.equal(spendLimitRatio(10000, 10000), 1)
	assert.equal(spendLimitRatio(8000, 10000), 0.8)
	assert.equal(spendLimitRatio(12000, 10000), 1)
	assert.equal(spendLimitRatio(5000, 0), 0)
})
