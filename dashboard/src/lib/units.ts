/** Trim trailing zeros: 2 → '2', 0.25 → '0.25'. */
export function formatGb(value: number): string {
	return Number.isInteger(value) ? `${value}` : `${value}`.replace(/\.?0+$/, '')
}

/** A vCPU count as a decimal, the way cloud providers list it: 0.125 → '0.125'. */
export function formatVcpu(vcpus: number): string {
	return formatGb(vcpus)
}

/** Memory in megabytes as a label: 512 → '512 MB', 4096 → '4 GB'. */
export function formatMemory(megabytes: number): string {
	if (megabytes < 1024) return `${megabytes} MB`

	const gigabytes = megabytes / 1024
	return `${Number.isInteger(gigabytes) ? gigabytes : gigabytes.toFixed(1)} GB`
}

export function gigabytesToMegabytes(gigabytes: number): number {
	return Math.round(gigabytes * 1024)
}
