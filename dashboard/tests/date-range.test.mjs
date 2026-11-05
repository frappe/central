import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/dateRange.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{ exports },
)
const { parseDateRange } = exports

const today = '2026-11-04'

const ranges = {
	'15 oct - 19 oct': ['2026-10-15', '2026-10-19'],
	'15 oct -19oct': ['2026-10-15', '2026-10-19'],
	'oct15-oct19': ['2026-10-15', '2026-10-19'],
	'15oct to 19oct': ['2026-10-15', '2026-10-19'],
	'15 oct to19 oct': ['2026-10-15', '2026-10-19'],
	'Oct 15, Oct 19': ['2026-10-15', '2026-10-19'],
	'october 15 - october 19': ['2026-10-15', '2026-10-19'],
	'15-19 oct': ['2026-10-15', '2026-10-19'],
	'15 oct - 19': ['2026-10-15', '2026-10-19'],
	'19 oct - 15 oct': ['2026-10-15', '2026-10-19'],
	'15 Oct to 19 Oct': ['2026-10-15', '2026-10-19'],
	'15 oct': ['2026-10-15', '2026-10-15'],
	'15 dec': ['2025-12-15', '2025-12-15'],
	'28 dec - 3 jan': ['2025-12-28', '2026-01-03'],
	'15 October 2025 - 2 jan 2026': ['2025-10-15', '2026-01-02'],
	'4 nov': ['2026-11-04', '2026-11-04'],
}

test('typed reads resolve to ISO ranges', () => {
	for (const [input, expected] of Object.entries(ranges)) {
		const result = parseDateRange(input, today)
		assert.notEqual(result, null, input)
		assert.deepEqual([...result], expected, input)
	}
})

const relativeRanges = {
	today: ['2026-11-04', '2026-11-04'],
	yesterday: ['2026-11-03', '2026-11-03'],
	'7d': ['2026-10-29', '2026-11-04'],
	'last 7 days': ['2026-10-29', '2026-11-04'],
	'past 30 days': ['2026-10-06', '2026-11-04'],
	'2w': ['2026-10-22', '2026-11-04'],
	'1m': ['2026-10-04', '2026-11-04'],
	'last month': ['2026-10-04', '2026-11-04'],
	'6 months': ['2026-05-04', '2026-11-04'],
	'last year': ['2025-11-04', '2026-11-04'],
	'1y': ['2025-11-04', '2026-11-04'],
	'this week': ['2026-11-02', '2026-11-04'],
	'this month': ['2026-11-01', '2026-11-04'],
	mtd: ['2026-11-01', '2026-11-04'],
	'this year': ['2026-01-01', '2026-11-04'],
	ytd: ['2026-01-01', '2026-11-04'],
	'Last 6 Months': ['2026-05-04', '2026-11-04'],
}

test('relative reads resolve to ISO ranges', () => {
	for (const [input, expected] of Object.entries(relativeRanges)) {
		const result = parseDateRange(input, today)
		assert.notEqual(result, null, input)
		assert.deepEqual([...result], expected, input)
	}
	assert.deepEqual(
		[...parseDateRange('1m', '2026-03-31')],
		['2026-02-28', '2026-03-31'],
	)
})

test('unreadable input returns null', () => {
	for (const input of [
		'',
		'   ',
		'abc',
		'31 feb',
		'15 - 19',
		'15 oct - 19 nov - 1 dec',
		'40 oct',
		'15 xyz',
		'0d',
		'last',
		'7x',
		'this decade',
	]) {
		assert.equal(parseDateRange(input, today), null, input)
	}
})
