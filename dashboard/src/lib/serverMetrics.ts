import type { MetricPoint } from '@/types/servers'

export type MetricRow = Record<string, Date | number | null>

type RateField =
	| 'received_bytes_per_second'
	| 'sent_bytes_per_second'
	| 'disk_read_bytes_per_second'
	| 'disk_write_bytes_per_second'

export interface MetricChart {
	key: string
	title: string
	series: string[]
	colors: number[]
	format: (value: number) => string
	rows: MetricRow[]
	max?: number
	interval?: number
	formatValue?: (value: number) => string
}

const MINIMUM_RATE_RANGE = 10 * 1024

const RATE_UNITS = ['B/s', 'KB/s', 'MB/s', 'GB/s']

// Choose one axis unit and evenly spaced ticks, with at least a 10 KB/s range.
const getRateScale = (values: (number | null)[]) => {
	const peak = Math.max(0, ...values.map((value) => value ?? 0))
	const { divisor, unit } = getRateUnit(Math.max(peak, MINIMUM_RATE_RANGE))
	const upperBound = Math.max(MINIMUM_RATE_RANGE, peak * 1.05) / divisor
	const desiredInterval = upperBound / 4
	const magnitude = 10 ** Math.floor(Math.log10(desiredInterval))
	const tickStep =
		[1, 2, 2.5, 5, 10].find((step) => step * magnitude >= desiredInterval) ?? 10
	const interval = tickStep * magnitude
	const max = Math.ceil(upperBound / interval) * interval

	return { divisor, unit, max, interval }
}

// Format an individual rate in its own unit so small values keep their precision.
export const formatRate = (bytesPerSecond: number): string => {
	const { divisor, unit } = getRateUnit(bytesPerSecond)
	const value = Number((bytesPerSecond / divisor).toPrecision(3))
	return `${value} ${unit}`
}

const scale = (value: number | null, divisor: number) =>
	value == null ? null : value / divisor

const toDate = (seconds: number): Date => new Date(seconds * 1000)

// Scale all rate series to a shared axis while keeping independent value formatting.
const getRateChart = (
	key: string,
	title: string,
	points: MetricPoint[],
	colors: number[],
	series: Record<string, RateField>,
): MetricChart => {
	const fields = Object.entries(series)
	const rate = getRateScale(
		points.flatMap((point) => fields.map(([, field]) => point[field])),
	)
	const rows = points.map((point) => {
		const row: MetricRow = { time: toDate(point.time) }

		for (const [label, field] of fields)
			row[label] = scale(point[field], rate.divisor)

		return row
	})

	return {
		key,
		title,
		series: Object.keys(series),
		colors,
		max: rate.max,
		interval: rate.interval,
		formatValue: (value) => formatRate(value * rate.divisor),
		format: (value) => `${Number(value.toFixed(1))} ${rate.unit}`,
		rows,
	}
}

// Return the latest sample and peak for each series without replacing missing samples.
export const getChartSeriesSummaries = (chart: MetricChart) =>
	chart.series.map((name) => {
		const values = chart.rows
			.map((row) => row[name])
			.filter((value): value is number => typeof value === 'number')
		const current = chart.rows[chart.rows.length - 1]?.[name]
		const format = chart.formatValue ?? chart.format

		return {
			name,
			hasSamples: values.length > 0,
			current: typeof current === 'number' ? format(current) : 'No sample',
			peak: values.length ? format(Math.max(...values)) : 'No samples',
		}
	})

export const formatSampleInterval = (seconds: number): string => {
	if (seconds % 3600 === 0)
		return seconds === 3600 ? 'hour' : `${seconds / 3600} hours`

	if (seconds % 60 === 0) return `${seconds / 60} min`

	return `${seconds} sec`
}

export const METRIC_PERIODS = [
	{ label: '1 hour', short: '1h', value: '1h' },
	{ label: '24 hours', short: '24h', value: '24h' },
	{ label: '7 days', short: '7d', value: '7d' },
	{ label: '14 days', short: '14d', value: '14d' },
	{ label: '30 days', short: '30d', value: '30d' },
	{ label: 'Custom', short: null, value: 'custom' },
]

export const getChartTimeGrain = (points: MetricPoint[]) => {
	const span = points.length
		? points[points.length - 1].time - points[0].time
		: 0
	if (span <= 86400) return 'minute'

	return span <= 7 * 86400 ? 'hour' : 'day'
}

export const getMetricCharts = (
	points: MetricPoint[],
	memoryGigabytes: number,
): MetricChart[] => [
	{
		key: 'cpu',
		title: 'CPU',
		series: ['CPU'],
		colors: [1],
		format: (value) => `${Number(value.toFixed(1))}%`,
		max: 100,
		rows: points.map((point) => ({
			time: toDate(point.time),
			CPU: point.cpu_percent,
		})),
	},
	{
		key: 'memory',
		title: 'Memory',
		series: ['Used'],
		colors: [5],
		format: (value) => `${Number(value.toFixed(2))} GB`,
		max: memoryGigabytes,
		rows: points.map((point) => ({
			time: toDate(point.time),
			Used: Math.min(point.memory_bytes / 1024 ** 3, memoryGigabytes),
		})),
	},
	getRateChart('network', 'Network', points, [3, 9], {
		Received: 'received_bytes_per_second',
		Sent: 'sent_bytes_per_second',
	}),
	getRateChart('disk', 'Disk I/O', points, [2, 7], {
		Read: 'disk_read_bytes_per_second',
		Write: 'disk_write_bytes_per_second',
	}),
]

// Choose the largest rate unit that fits the value, up to GB/s.
function getRateUnit(bytesPerSecond: number) {
	let unitIndex = 0
	let divisor = 1

	while (
		bytesPerSecond >= divisor * 1024 &&
		unitIndex < RATE_UNITS.length - 1
	) {
		divisor *= 1024
		unitIndex += 1
	}

	return { divisor, unit: RATE_UNITS[unitIndex] }
}
