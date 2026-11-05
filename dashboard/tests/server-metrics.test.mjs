import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/serverMetrics.ts', import.meta.url),
	'utf8',
)
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{ exports },
)

const point = (rates = {}) => ({
	time: 1,
	cpu_percent: 0,
	memory_bytes: 0,
	received_bytes_per_second: 0,
	sent_bytes_per_second: 0,
	disk_read_bytes_per_second: 0,
	disk_write_bytes_per_second: 0,
	...rates,
})

test('idle rate charts start with a 10 KB/s range, including missing samples', () => {
	for (const points of [
		[],
		[point()],
		[point({ received_bytes_per_second: null })],
	]) {
		const charts = exports.getMetricCharts(points, 1).slice(2)
		for (const chart of charts) {
			assert.equal(chart.max, 10)
			assert.equal(chart.format(chart.max), '10 KB/s')
		}
	}
})

test('rate ranges include the larger series and retain KB/s or MB/s precision', () => {
	const charts = exports
		.getMetricCharts(
			[
				point({
					received_bytes_per_second: 140 * 1024,
					sent_bytes_per_second: 900 * 1024,
					disk_read_bytes_per_second: 32 * 1024,
					disk_write_bytes_per_second: 1.5 * 1024 ** 2,
				}),
			],
			1,
		)
		.slice(2)
	assert.equal(charts[0].format(charts[0].max), '1000 KB/s')
	assert.equal(charts[1].format(charts[1].max), '2 MB/s')
	for (const chart of charts)
		for (const series of chart.series)
			assert.ok(chart.rows[0][series] <= chart.max)
})

test('summaries and tooltips preserve small rates alongside MB/s spikes', () => {
	const chart = exports.getMetricCharts(
		[
			point({
				received_bytes_per_second: 2 * 1024 ** 2,
				sent_bytes_per_second: 900 * 1024,
			}),
			point({
				received_bytes_per_second: 8.5 * 1024,
				sent_bytes_per_second: 512,
			}),
		],
		1,
	)[2]
	const summaries = exports.getChartSeriesSummaries(chart)
	assert.equal(summaries[0].value, '1 MB/s')
	assert.equal(summaries[0].peak, '2 MB/s')
	assert.equal(summaries[1].value, '450 KB/s')
	assert.equal(summaries[1].peak, '900 KB/s')
	assert.equal(chart.formatValue(chart.rows[1].Received), '8.5 KB/s')
	assert.equal(chart.formatValue(0), '0 B/s')
	assert.ok(chart.max > Math.max(chart.rows[0].Received, chart.rows[0].Sent))
	assert.ok(
		Math.abs(
			chart.max / chart.interval - Math.round(chart.max / chart.interval),
		) < 1e-10,
	)
})

test('averages ignore missing samples and keep measured zeroes', () => {
	const chart = exports.getMetricCharts(
		[
			point({ received_bytes_per_second: 2048 }),
			point({ received_bytes_per_second: null, sent_bytes_per_second: null }),
		],
		1,
	)[2]
	const summaries = exports.getChartSeriesSummaries(chart)
	assert.equal(summaries[0].value, '2 KB/s')
	assert.equal(summaries[0].peak, '2 KB/s')
	assert.equal(summaries[1].value, '0 B/s')
	assert.equal(exports.formatRate(0.01), '0.01 B/s')
})

test('all four rate series average their samples and keep their peaks', () => {
	const charts = exports
		.getMetricCharts(
			[
				point({
					received_bytes_per_second: 2048,
					sent_bytes_per_second: 4096,
					disk_read_bytes_per_second: 0,
					disk_write_bytes_per_second: 2048,
				}),
				point({
					received_bytes_per_second: 6144,
					sent_bytes_per_second: 0,
					disk_read_bytes_per_second: 8192,
					disk_write_bytes_per_second: 6144,
				}),
			],
			4,
		)
		.slice(2)
	const summaries = charts.flatMap(exports.getChartSeriesSummaries)
	assert.deepEqual(
		Array.from(summaries, (summary) => summary.value),
		['4 KB/s', '2 KB/s', '4 KB/s', '4 KB/s'],
	)
	assert.deepEqual(
		Array.from(summaries, (summary) => summary.peak),
		['6 KB/s', '4 KB/s', '8 KB/s', '6 KB/s'],
	)
})

test('CPU and memory retain the latest reading, including missing CPU samples', () => {
	const points = [
		point({ cpu_percent: 70, memory_bytes: 1024 ** 3 }),
		point({ cpu_percent: 20, memory_bytes: 2 * 1024 ** 3 }),
	]
	const charts = exports.getMetricCharts(points, 4)
	assert.equal(exports.getChartSeriesSummaries(charts[0])[0].value, '20%')
	assert.equal(exports.getChartSeriesSummaries(charts[0])[0].peak, '70%')
	assert.equal(exports.getChartSeriesSummaries(charts[1])[0].value, '2 GB')
	points.push(point({ cpu_percent: null }))
	assert.equal(
		exports.getChartSeriesSummaries(exports.getMetricCharts(points, 4)[0])[0]
			.value,
		'No sample',
	)
})

test('rate averages do not treat missing data as zero', () => {
	for (const points of [
		[],
		[
			point({
				received_bytes_per_second: null,
				sent_bytes_per_second: null,
				disk_read_bytes_per_second: null,
				disk_write_bytes_per_second: null,
			}),
		],
	]) {
		for (const chart of exports.getMetricCharts(points, 4).slice(2)) {
			for (const summary of exports.getChartSeriesSummaries(chart)) {
				assert.equal(summary.value, 'No sample')
				assert.equal(summary.hasSamples, false)
			}
		}
	}
})
