<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import FirewallRuleRow from '@/components/servers/firewall/FirewallRuleRow.vue'
import {
	ANYWHERE_IPV4,
	ANYWHERE_IPV6,
	type FirewallRule,
	type FirewallRules,
	getService,
	PRIVATE_NETWORK,
	SERVICES,
	WIREGUARD_NETWORK,
} from '@/lib/firewall'

type Direction = keyof FirewallRules

interface Props {
	rules: FirewallRules
	disabled: boolean
	/** Names for known addresses, such as the team's WireGuard VPN devices. */
	names: Record<string, string>
	/** Changes when the owner replaces the rules, so the rows start again. */
	revision?: number
}

const props = withDefaults(defineProps<Props>(), { revision: 0 })
const emit = defineEmits<{
	/** `source` names the edited field, so an undo history can merge a burst of typing. */
	update: [rules: FirewallRules, source?: string]
	/** True while a row holds a typed address that was not added. */
	invalid: [invalid: boolean]
}>()

const directions: Direction[] = ['inbound', 'outbound']

// Rows keep local state and are keyed by index, so a removed row remounts the rest.
const removals = ref(0)
const incomplete = ref<Record<string, boolean>>({})
const hasIncomplete = computed(() =>
	Object.values(incomplete.value).some(Boolean),
)

watch(hasIncomplete, (invalid) => emit('invalid', invalid))
watch(
	() => props.revision,
	() => {
		incomplete.value = {}
	},
)

// structuredClone refuses Vue's reactive objects, and the rules are plain JSON.
const copy = (): FirewallRules => JSON.parse(JSON.stringify(props.rules))

function updateRule(
	direction: Direction,
	index: number,
	rule: FirewallRule,
): void {
	const rules = copy()
	rules[direction][index] = rule
	emit('update', rules, `${direction}:${index}`)
}

function removeRule(direction: Direction, index: number): void {
	const rules = copy()
	rules[direction].splice(index, 1)
	incomplete.value = {}
	removals.value++
	emit('update', rules)
}

function addRule(direction: Direction): void {
	const used = props.rules[direction].map((rule) => getService(rule).label)
	const service =
		SERVICES.find(
			(item) =>
				(direction === 'inbound'
					? ['HTTPS', 'HTTP', 'SSH']
					: ['All traffic']
				).includes(item.label) && !used.includes(item.label),
		) ?? SERVICES.find((item) => item.label === 'Custom TCP')!
	const rules = copy()
	rules[direction].push({
		protocol: service.protocol,
		ports: service.ports ?? '',
		cidrs: ['SSH', 'Custom TCP', 'Custom UDP'].includes(service.label)
			? []
			: ['0.0.0.0/0', '::/0'],
	})
	emit('update', rules)
}

function getAddressOptions(direction: Direction): string[] {
	const used = props.rules[direction].flatMap((rule) => rule.cidrs)
	return direction === 'inbound'
		? [
				ANYWHERE_IPV4,
				ANYWHERE_IPV6,
				PRIVATE_NETWORK,
				WIREGUARD_NETWORK,
				...Object.keys(props.names),
				...used,
			]
		: [ANYWHERE_IPV4, ANYWHERE_IPV6, ...used]
}
</script>

<template>
	<div class="space-y-6">
		<section
			v-for="direction in directions"
			:key="direction"
			:aria-label="direction === 'inbound' ? __('Incoming rules') : __('Outgoing rules')"
		>
			<h3 class="px-2 pb-1 text-sm-medium text-ink-gray-8">
				{{ direction === 'inbound' ? __('Incoming') : __('Outgoing') }}
			</h3>

			<div
				class="hidden h-8 items-center gap-x-4 px-2 text-sm text-ink-gray-5 sm:grid sm:grid-cols-[9rem_6rem_minmax(0,1fr)_1.75rem]"
				aria-hidden="true"
			>
				<span>{{ __('Service') }}</span>
				<span>{{ __('Port') }}</span>
				<span
					>{{ direction === 'inbound' ? __('Allowed from') : __('Allowed to') }}</span
				>
			</div>

			<FirewallRuleRow
				v-for="(rule, index) in rules[direction]"
				:key="`${revision}:${removals}:${index}`"
				:rule="rule"
				:index="index"
				:incoming="direction === 'inbound'"
				:disabled="disabled"
				:options="getAddressOptions(direction)"
				:names="names"
				@update="updateRule(direction, index, $event)"
				@remove="removeRule(direction, index)"
				@invalid="incomplete[`${direction}:${index}`] = $event"
			/>
			<p
				v-if="!rules[direction].length"
				class="flex min-h-10 items-center px-2 text-sm text-ink-gray-5"
			>
				{{ direction === 'inbound' ? __('No incoming connections are allowed.') : __('No outgoing connections are allowed.') }}
			</p>

			<div v-if="!disabled" class="pt-2">
				<Button
					size="sm"
					variant="ghost"
					icon-left="lucide-plus"
					:label="direction === 'inbound' ? __('Add incoming rule') : __('Add outgoing rule')"
					@click="addRule(direction)"
				/>
			</div>
		</section>
	</div>
</template>
