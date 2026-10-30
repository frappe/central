import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const load = () => {
	const source = readFileSync(
		new URL('../src/lib/serverMap.ts', import.meta.url),
		'utf8',
	)
	const exports = {}

	runInNewContext(
		typescript.transpileModule(source, {
			compilerOptions: { module: typescript.ModuleKind.CommonJS },
		}).outputText,
		{
			exports,
			require: () => ({ displayStatus: String, formatMemory: String }),
		},
	)

	return exports
}

const rowsIn = (cluster, count) =>
	Array.from({ length: count }, () => ({ cluster }))

test('a region with more than 10 servers is crowded', () => {
	const { hasCrowdedRegion } = load()

	assert.equal(hasCrowdedRegion(rowsIn('in-mumbai', 11)), true)
})

test('exactly 10 servers in a region is not crowded', () => {
	const { hasCrowdedRegion } = load()

	assert.equal(hasCrowdedRegion(rowsIn('in-mumbai', 10)), false)
})

test('servers spread over regions are not crowded', () => {
	const { hasCrowdedRegion } = load()
	const rows = [...rowsIn('in-mumbai', 8), ...rowsIn('eu-frankfurt', 8)]

	assert.equal(hasCrowdedRegion(rows), false)
})
