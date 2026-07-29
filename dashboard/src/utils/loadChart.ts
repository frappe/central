export type LoadPoint = {
	time: number
	Load1?: number
	Load5?: number
	Load15?: number
}

export const LOAD_SERIES = [
	{ key: 'Load1' as const, label: 'Load 1m', color: '#238b5b' },
	{ key: 'Load5' as const, label: 'Load 5m', color: '#d17c00' },
	{ key: 'Load15' as const, label: 'Load 15m', color: '#db2828' },
]

export function peakLoad(points: LoadPoint[]): number {
	if (!points.length) return 0
	return Math.max(
		0,
		...points.flatMap((point) => [
			point.Load1 ?? 0,
			point.Load5 ?? 0,
			point.Load15 ?? 0,
		]),
	)
}

/** Rows for AxisChart — series `name` is the y-value key. */
export function toLoadChartRows(points: LoadPoint[]): Record<string, unknown>[] {
	return points.map((point) => {
		const time =
			point.time > 1e12 ? new Date(point.time) : new Date(point.time * 1000)
		return {
			time,
			'Load 1m': point.Load1 ?? 0,
			'Load 5m': point.Load5 ?? 0,
			'Load 15m': point.Load15 ?? 0,
		}
	})
}
