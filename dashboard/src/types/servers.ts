import type { VirtualMachineRow } from '@/composables/useServers'

export interface MetricPoint {
	time: number
	is_up: boolean
	cpu_percent: number | null
	memory_bytes: number
	disk_used_bytes: number
	disk_total_bytes: number
	disk_read_bytes_per_second: number
	disk_write_bytes_per_second: number
	received_bytes_per_second: number | null
	sent_bytes_per_second: number | null
}

export interface ServerMonitoring {
	available: boolean
	points?: MetricPoint[]
	sample_interval_seconds?: number
}

export interface MetricsRange {
	period: string
	start: string | null
	end: string | null
}

export interface ServerOverview {
	server: VirtualMachineRow & {
		creation: string
		plan_title: string | null
		plan_rate: number | null
		plan_currency: string | null
		plan_billing_cycle: string | null
		team_name: string
		ssh_command: string | null
		ssh_keys: { title: string; fingerprint: string }[]
		has_public_ipv6: 0 | 1
		is_firewall_enabled: 0 | 1
		region_details: {
			display_name: string | null
			provider: string | null
			country_code: string | null
		}
	}
}
