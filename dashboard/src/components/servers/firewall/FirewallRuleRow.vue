<script setup lang="ts">
import { Button, Combobox, FormControl, Select } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import Chip from '@/components/common/Chip.vue'
import {
	ANYWHERE_IPV4,
	ANYWHERE_IPV6,
	type FirewallRule,
	getAddressLabel,
	getCidrError,
	getService,
	isExposedRule,
	isValidPortRange,
	SERVICES,
	toCidr,
} from '@/lib/firewall'
import { __ } from '@/lib/translate'

interface Props {
	rule: FirewallRule
	index: number
	incoming: boolean
	disabled: boolean
	/** The named sources and the addresses of the other rules, offered in the list. */
	options: string[]
	/** Names for known addresses, such as the team's WireGuard VPN devices. */
	names: Record<string, string>
}

const props = defineProps<Props>()
const emit = defineEmits<{
	update: [rule: FirewallRule]
	remove: []
	invalid: [invalid: boolean]
}>()

// Opening one of these to the internet is rarely intended, so they start closed.
const PRIVATE_SERVICES = [
	'SSH',
	'MariaDB',
	'PostgreSQL',
	'Redis',
	'Custom TCP',
	'Custom UDP',
]

const address = ref('')
const addressError = ref('')
const portTouched = ref(false)

const selectedService = ref(getService(props.rule).label)
const service = computed(
	() => SERVICES.find((item) => item.label === selectedService.value)!,
)
const anyone = computed(
	() =>
		props.rule.cidrs.includes(ANYWHERE_IPV4) &&
		props.rule.cidrs.includes(ANYWHERE_IPV6),
)

// Typed text that was never added would be silently dropped on apply. An error belongs to
// the text that caused it, so it goes when the text changes.
watch(
	address,
	() => {
		addressError.value = ''
		emit('invalid', !!address.value.trim())
	},
	{ flush: 'sync' },
)

const portLabel = computed(() => {
	if (props.rule.protocol === 'any') return 'All'
	if (props.rule.protocol === 'icmp') return 'No ports'
	return props.rule.ports || 'All'
})
const portError = computed(() =>
	isValidPortRange(props.rule.ports)
		? ''
		: 'Use a port from 1 to 65535, or a range such as 8000-8100.',
)
const isExposed = computed(() => props.incoming && isExposedRule(props.rule))
const serviceOptions = SERVICES.map((item) => ({
	label: item.label,
	value: item.label,
}))
const typedCidr = computed(() => toCidr(address.value))
// The named sources and known addresses this rule does not have yet, then the typed address.
const sourceOptions = computed(() => [
	...[...new Set(props.options)]
		.filter((cidr) => !props.rule.cidrs.includes(cidr))
		.map((cidr) => {
			const label = getAddressLabel(cidr, props.names)
			return {
				label,
				value: cidr,
				description: label === cidr ? undefined : cidr,
			}
		}),
	{
		type: 'custom' as const,
		key: 'typed-address',
		label: __('Add this address'),
		icon: 'lucide-plus',
		condition: () => isNewAddress.value,
		onClick: addTypedAddress,
	},
])
const isNewAddress = computed(
	() =>
		!!address.value.trim() &&
		!getCidrError(address.value) &&
		!props.rule.cidrs.includes(typedCidr.value),
)

// A named source shows its real range on hover, so the name never hides the address.
function getTooltip(cidr: string): string | undefined {
	return getAddressLabel(cidr, props.names) === cidr ? undefined : cidr
}

function changeService(label: string): void {
	const next = SERVICES.find((item) => item.label === label)!
	selectedService.value = label
	portTouched.value = false
	address.value = ''
	emit('update', {
		...props.rule,
		protocol: next.protocol,
		ports: next.ports ?? '',
		cidrs:
			PRIVATE_SERVICES.includes(label) && anyone.value ? [] : props.rule.cidrs,
	})
}

function addSource(cidr: string | null): void {
	if (!cidr) return

	emit('update', {
		...props.rule,
		cidrs: [...new Set([...props.rule.cidrs, cidr])],
	})
	address.value = ''
}

function addTypedAddress(): void {
	addressError.value = address.value.trim() ? getCidrError(address.value) : ''
	if (isNewAddress.value) addSource(typedCidr.value)
}

// The list drops the typed text when it closes, so a valid address is added, not lost.
function keepTypedAddress(isOpen: boolean): void {
	if (isOpen) return

	if (isNewAddress.value) addSource(typedCidr.value)
	else address.value = ''
}

// Backspace in the empty field removes the last source, as in other chip fields.
function removeLastAddress(): void {
	if (!address.value && props.rule.cidrs.length)
		removeAddress(props.rule.cidrs[props.rule.cidrs.length - 1])
}

function removeAddress(cidr: string): void {
	emit('update', {
		...props.rule,
		cidrs: props.rule.cidrs.filter((item) => item !== cidr),
	})
}
</script>

<template>
	<div
		class="grid grid-cols-[minmax(0,1fr)_6rem_1.75rem] items-start gap-x-4 gap-y-2 px-2 py-1.5 sm:grid-cols-[9rem_6rem_minmax(0,1fr)_1.75rem]"
	>
		<!-- A disabled Combobox keeps full-strength text, so a read-only row uses the dimmed Select. -->
		<Select
			v-if="disabled"
			:model-value="service.label"
			:options="serviceOptions"
			:aria-label="`Service, rule ${index + 1}`"
			disabled
			class="w-full"
		/>
		<Combobox
			v-else
			:model-value="service.label"
			:options="serviceOptions"
			:aria-label="`Service, rule ${index + 1}`"
			class="w-full"
			@update:model-value="changeService"
		/>

		<FormControl
			v-if="service.ports === null"
			:model-value="rule.ports"
			:aria-label="`Port, rule ${index + 1}`"
			:disabled="disabled"
			:error="portTouched ? portError : ''"
			placeholder="All ports"
			class="w-full"
			@focus="portTouched = false"
			@blur="portTouched = true"
			@update:model-value="(ports: string) => emit('update', { ...rule, ports })"
		/>
		<p
			v-else
			class="flex h-7 items-center px-2 text-base"
			:class="disabled ? 'text-ink-gray-5' : 'text-ink-gray-7'"
		>
			{{ portLabel }}
		</p>

		<!-- The remove button has its own padding, so the field reaches 8px closer to it. -->
		<div
			class="order-last col-span-3 min-w-0 space-y-2 sm:order-none sm:col-span-1 sm:-mr-2"
		>
			<div
				class="flex min-h-7 flex-wrap items-center gap-1 rounded-4 bg-surface-gray-2 px-1 focus-within:focus-ring"
				:class="{ 'pr-2': disabled }"
				@keydown.enter="addTypedAddress"
				@keydown.backspace="removeLastAddress"
			>
				<Chip
					v-for="cidr in rule.cidrs"
					:key="cidr"
					:label="getAddressLabel(cidr, names)"
					:tooltip="getTooltip(cidr)"
					:remove-label="disabled ? undefined : `Remove ${getAddressLabel(cidr, names)}`"
					@remove="removeAddress(cidr)"
				/>

				<Combobox
					v-if="!disabled"
					v-model:query="address"
					:model-value="null"
					:options="sourceOptions"
					variant="ghost"
					open-on-focus
					:aria-label="`${incoming ? 'Allowed from' : 'Allowed to'}, rule ${index + 1}`"
					:placeholder="rule.cidrs.length ? __('Add another') : __('Choose who, or type an IP address or range')"
					:empty-text="__('Type an IP address or range, such as 203.0.113.7')"
					class="min-w-32 flex-1 !px-1"
					@update:model-value="addSource"
					@update:open="keepTypedAddress"
				/>
				<span
					v-else-if="!rule.cidrs.length"
					class="px-1.5 text-sm text-ink-gray-5"
				>
					{{ __('No address') }}
				</span>
			</div>
			<p v-if="addressError" class="text-p-sm text-ink-red-6" role="alert">
				{{ addressError }}
			</p>

			<p
				v-if="isExposed"
				class="flex items-center gap-1.5 text-p-sm text-ink-amber-7"
			>
				<span
					class="lucide-triangle-alert size-4 shrink-0"
					aria-hidden="true"
				/>
				This exposes {{ service.label }} to the public internet.
			</p>
		</div>

		<Button
			variant="ghost"
			icon="lucide-trash-2"
			tooltip="Remove rule"
			:aria-label="`Remove ${service.label} rule`"
			:disabled="disabled"
			@click="emit('remove')"
		/>
	</div>
</template>
