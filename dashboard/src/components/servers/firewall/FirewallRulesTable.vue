<script setup lang="ts">
import { computed } from 'vue'
import {
	type FirewallRule,
	type FirewallRules,
	getAddressLabel,
	getPortLabel,
	getService,
	isCoveredBy,
	isSameRule,
} from '@/lib/firewall'
import { __ } from '@/lib/translate'
import type { FirewallRuleset } from '@/types/firewallRulesets'

interface Props {
	rules: FirewallRules
	/** Names for known addresses, such as the team's WireGuard VPN devices. */
	names: Record<string, string>
	/** The rulesets the rules come from. Each rule then names its rulesets. */
	sources?: FirewallRuleset[]
}

const props = defineProps<Props>()

const directions = computed(() => [
	{ key: 'inbound' as const, label: __('Incoming') },
	{ key: 'outbound' as const, label: __('Outgoing') },
])

const getAddresses = (rule: FirewallRule): string =>
	rule.cidrs.map((cidr) => getAddressLabel(cidr, props.names)).join(', ')

// In a merged list, a rule that a wider rule already allows changes nothing.
const isCovered = (rule: FirewallRule, direction: keyof FirewallRules) =>
	!!props.sources &&
	props.rules[direction].some((other) => isCoveredBy(rule, other))

function getSources(
	rule: FirewallRule,
	direction: keyof FirewallRules,
): string {
	return (props.sources ?? [])
		.filter((ruleset) =>
			ruleset.rules[direction].some((other) => isSameRule(rule, other)),
		)
		.map((ruleset) => ruleset.title)
		.join(', ')
}
</script>

<template>
	<div class="space-y-4">
		<section
			v-for="direction in directions"
			:key="direction.key"
			:aria-label="direction.label"
		>
			<h4 class="pb-1 text-sm text-ink-gray-5">{{ direction.label }}</h4>
			<ul v-if="rules[direction.key].length">
				<li
					v-for="(rule, index) in rules[direction.key]"
					:key="index"
					class="grid gap-x-4 py-1.5 text-base"
					:class="[
						sources ? 'grid-cols-[7rem_5rem_minmax(0,1fr)_minmax(0,1fr)]' : 'grid-cols-[7rem_5rem_minmax(0,1fr)]',
						isCovered(rule, direction.key) ? 'text-ink-gray-4' : 'text-ink-gray-7',
					]"
					:title="isCovered(rule, direction.key) ? __('A wider rule already allows this.') : undefined"
				>
					<span>{{ getService(rule).label }}</span>
					<span>{{ getPortLabel(rule) }}</span>
					<!-- The title holds the real ranges, so a name never hides an address. -->
					<span :title="rule.cidrs.join(', ')">{{ getAddresses(rule) }}</span>
					<span
						v-if="sources"
						class="truncate text-ink-gray-5"
						:title="getSources(rule, direction.key)"
					>
						{{ getSources(rule, direction.key) }}
					</span>
				</li>
			</ul>
			<p v-else class="py-1.5 text-base text-ink-gray-5">
				{{ __('No connections are allowed.') }}
			</p>
		</section>
	</div>
</template>
