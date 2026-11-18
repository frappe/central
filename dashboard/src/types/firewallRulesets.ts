import type { FirewallRules } from '@/lib/firewall'

/** The fields Central's firewall ruleset list returns. */
export interface FirewallRuleset {
	name: string
	title: string
	rules: FirewallRules
	/** The servers that did not get the latest rules, if any. */
	last_sync_error: string | null
	server_count: number
}
