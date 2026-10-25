import type { VirtualMachineRow } from '@/composables/useServers'
import type { FirewallRules } from '@/lib/firewall'

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

/** A team key that can sign in to one server. */
export interface ServerSSHKey {
	name: string
	title: string
	fingerprint: string
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
		ssh_keys: ServerSSHKey[]
		has_public_ipv6: 0 | 1
		is_firewall_enabled: 0 | 1
		is_termination_protected: 0 | 1
		has_ipv4_internet: 0 | 1
		has_wireguard_access: 0 | 1
		/** Null until Central first reads the firewall from the region. */
		firewall_rules: FirewallRules | null
		/** Set only for a System Manager. */
		operator_links: {
			desk_url: string
			/** Null until the region has an Atlas URL and the server an Atlas ID. */
			atlas_url: string | null
		} | null
		region_details: {
			display_name: string | null
			provider: string | null
			country_code: string | null
			has_wireguard_gateway: 0 | 1
		}
	}
}
