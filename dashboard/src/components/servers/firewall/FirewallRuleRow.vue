<script setup lang="ts">
import { Button, Combobox, FormControl, Select } from 'frappe-ui'
import { computed, ref, useId, watch } from 'vue'
import {
	ANYWHERE_IPV4,
	ANYWHERE_IPV6,
	type FirewallRule,
	getCidrError,
	getService,
	isValidPortRange,
	SERVICES,
	toCidr,
} from '@/lib/firewall'

interface Props {
	rule: FirewallRule
	index: number
	incoming: boolean
	disabled: boolean
	/** Addresses used by the other rules, offered while typing a new one. */
	options: string[]
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
const EXPOSED_SERVICES = ['MariaDB', 'PostgreSQL', 'Redis', 'All traffic']

const suggestionsId = useId()
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

// Typed text that was never added would be silently dropped on apply.
watch(
	[address, anyone],
	() => emit('invalid', !anyone.value && !!address.value.trim()),
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
const isExposed = computed(
	() =>
		anyone.value &&
		props.incoming &&
		EXPOSED_SERVICES.includes(service.value.label),
)
const serviceOptions = SERVICES.map((item) => ({
	label: item.label,
	value: item.label,
}))
const suggestions = computed(() =>
	[...new Set(props.options)].filter(
		(cidr) => !props.rule.cidrs.includes(cidr),
	),
)

function clearAddress(): void {
	address.value = ''
	addressError.value = ''
}

function changeService(label: string): void {
	const next = SERVICES.find((item) => item.label === label)!
	selectedService.value = label
	portTouched.value = false
	clearAddress()
	emit('update', {
		...props.rule,
		protocol: next.protocol,
		ports: next.ports ?? '',
		cidrs:
			PRIVATE_SERVICES.includes(label) && anyone.value ? [] : props.rule.cidrs,
	})
}

function changeAccess(value: string): void {
	clearAddress()
	emit('update', {
		...props.rule,
		cidrs: value === 'anyone' ? [ANYWHERE_IPV4, ANYWHERE_IPV6] : [],
	})
}

function addAddress(): void {
	const cidr = toCidr(address.value)
	addressError.value = getCidrError(address.value)
	if ([ANYWHERE_IPV4, ANYWHERE_IPV6].includes(cidr))
		addressError.value = 'Choose Anyone on the internet to allow all addresses.'
	if (addressError.value) return

	emit('update', {
		...props.rule,
		cidrs: [...new Set([...props.rule.cidrs, cidr])],
	})
	clearAddress()
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

		<div
			class="order-last col-span-3 min-w-0 space-y-2 sm:order-none sm:col-span-1"
		>
			<Select
				:model-value="anyone ? 'anyone' : 'specific'"
				:aria-label="`${incoming ? 'Allowed from' : 'Allowed to'}, rule ${index + 1}`"
				:options="[
					{ label: 'Anyone on the internet', value: 'anyone' },
					{ label: 'Specific addresses', value: 'specific' },
				]"
				:disabled="disabled"
				class="w-full"
				@update:model-value="changeAccess"
			/>

			<template v-if="!anyone">
				<ul v-if="rule.cidrs.length" class="flex flex-wrap gap-1.5">
					<li
						v-for="cidr in rule.cidrs"
						:key="cidr"
						class="inline-flex h-6 items-center rounded-3 bg-surface-gray-2 text-sm text-ink-gray-8"
						:class="disabled ? 'px-2' : 'pl-2'"
					>
						{{ cidr }}
						<Button
							v-if="!disabled"
							variant="ghost"
							size="xs"
							icon="lucide-x"
							:aria-label="`Remove ${cidr}`"
							@click="removeAddress(cidr)"
						/>
					</li>
				</ul>

				<template v-if="!disabled">
					<FormControl
						v-model="address"
						:aria-label="`Add an IP address or range, rule ${index + 1}`"
						:list="suggestions.length ? suggestionsId : undefined"
						placeholder="Add an IP address or range, then press Enter"
						:error="addressError"
						@keyup.enter="addAddress"
					>
						<template #suffix>
							<Button
								v-if="address.trim()"
								variant="ghost"
								size="xs"
								label="Add"
								@click="addAddress"
							/>
						</template>
					</FormControl>
					<datalist v-if="suggestions.length" :id="suggestionsId">
						<option v-for="cidr in suggestions" :key="cidr" :value="cidr" />
					</datalist>
				</template>
			</template>

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

<style scoped>
/* Chrome draws a dropdown arrow on inputs with suggestions, which reads as a select. */
:deep(input[list]::-webkit-calendar-picker-indicator) {
	display: none !important;
}
</style>
