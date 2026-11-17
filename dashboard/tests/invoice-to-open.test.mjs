import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/invoiceToOpen.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{ exports },
)
const { invoiceToOpen } = exports

function row(name, status, period_start, issued = true) {
	return { name, status, period_start, due_date: issued ? '2026-12-01' : null }
}

test('an overdue invoice beats an older outstanding one', () => {
	const rows = [
		row('INV-OLD', 'Outstanding', '2026-08-01'),
		row('INV-LATE', 'Overdue', '2026-09-01'),
	]
	assert.equal(invoiceToOpen(rows), 'INV-LATE')
})

test('the oldest outstanding invoice wins when none is overdue', () => {
	const rows = [
		row('INV-OCT', 'Outstanding', '2026-10-01'),
		row('INV-AUG', 'Outstanding', '2026-08-01'),
		row('INV-SEP', 'Outstanding', '2026-09-01'),
	]
	assert.equal(invoiceToOpen(rows), 'INV-AUG')
})

test('an invoice that is not issued is never chosen', () => {
	const rows = [
		row('INV-DRAFT', 'Overdue', '2026-07-01', false),
		row('INV-SEP', 'Outstanding', '2026-09-01'),
	]
	assert.equal(invoiceToOpen(rows), 'INV-SEP')
	assert.equal(invoiceToOpen([rows[0]]), null)
})

test('no open invoice gives null', () => {
	assert.equal(invoiceToOpen([]), null)
	assert.equal(invoiceToOpen([row('INV-PAID', 'Paid', '2026-09-01')]), null)
})

test('an owed invoice from long ago is still chosen', () => {
	const rows = [
		row('INV-SEP', 'Outstanding', '2026-09-01'),
		row('INV-2024', 'Outstanding', '2024-03-01'),
	]
	assert.equal(invoiceToOpen(rows), 'INV-2024')
})
