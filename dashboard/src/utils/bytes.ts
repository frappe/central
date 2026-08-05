/** Format a byte count for resource meters, e.g. "0.8 GB". */
export function formatBytes(value?: number | null): string {
	if (value == null || value < 0) return '—'
	const units = ['B', 'KB', 'MB', 'GB', 'TB']
	let amount = value
	let unit = 0
	while (amount >= 1024 && unit < units.length - 1) {
		amount /= 1024
		unit += 1
	}
	const rounded =
		amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)
	return `${rounded} ${units[unit]}`
}

/** Used÷total as a 0–100 percentage for progress bars. */
export function usagePercent(
	used?: number | null,
	total?: number | null,
): number {
	if (!used || !total) return 0
	return Math.min(100, Math.max(0, (used / total) * 100))
}
