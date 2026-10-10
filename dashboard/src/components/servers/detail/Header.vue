<script setup lang="ts">
import { Badge, Button, Dropdown } from 'frappe-ui'
import { computed } from 'vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import type { ServerCommand, VirtualMachineRow } from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'
import { formatPlanLabel } from '@/lib/planLabel'
import { statusVisual } from '@/lib/serverMap'
import { getServerMenu, type ServerMenuVerb } from '@/lib/serverMenu'
import { isSettingUp } from '@/lib/status'
import type { ServerOverview } from '@/types/servers'

interface Props {
	server: VirtualMachineRow
	details: ServerOverview['server'] | null
	actions: ServerActions
	siteUrl: string | null
	opening: boolean
	busy: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
	open: []
	pilot: []
	command: [command: Exclude<ServerCommand, 'terminate'>]
	console: []
	rename: []
	snapshot: []
	resize: []
	terminate: []
}>()

const visual = computed(() => statusVisual(props.server))
const isLocked = computed(() => !!props.server.pending_action)
const isRunning = computed(() => props.server.status === 'Running')
const isUbuntu = computed(() => props.server.image_offering === 'ubuntu')

const address = computed(
	() => props.server.public_ipv6 || props.server.public_ipv4,
)

const copy = async (value: string, label: string): Promise<void> => {
	if (await copyToClipboard(value)) {
		successToast(`${label} copied`)
		return
	}

	reportError(`${label} could not be copied. Select it and copy by hand.`)
}

const facts = computed(() => {
	const server = props.server
	const details = props.details
	const region = details?.region_details

	return [
		{
			icon: 'lucide-map-pin',
			label: region?.display_name || server.region,
		},
		{
			icon: 'lucide-layers',
			label: isUbuntu.value
				? 'Ubuntu'
				: `Frappe ${server.frappe_version || ''}`.trim(),
		},
		{
			icon: 'lucide-receipt',
			label:
				details &&
				formatPlanLabel({
					title: details.plan_title,
					rate: details.plan_rate,
					currency: details.plan_currency,
					billingCycle: details.plan_billing_cycle,
				}),
		},
	].filter((fact) => fact.label)
})

const canOpen = computed(
	() =>
		props.actions.open &&
		!isUbuntu.value &&
		!isSettingUp(props.server.status) &&
		(!!props.siteUrl || !!props.server.gateway_url),
)

// Overview and Open are the page itself and its primary button, so the menu omits them.
const handlers: Partial<Record<ServerMenuVerb, () => void>> = {
	pilot: () => emit('pilot'),
	start: () => emit('command', 'start'),
	stop: () => emit('command', 'stop'),
	restart: () => emit('command', 'restart'),
	resize: () => emit('resize'),
	snapshot: () => emit('snapshot'),
	console: () => emit('console'),
	rename: () => emit('rename'),
	terminate: () => emit('terminate'),
}

const menu = computed(() =>
	getServerMenu(props.server, props.actions, (verb) => handlers[verb]?.(), {
		opensSite: !!props.siteUrl,
		isOnServerPage: true,
	}),
)
</script>

<template>
	<header
		class="flex flex-col gap-4 rounded-6 bg-surface-gray-1 p-4 md:flex-row md:items-center md:justify-between"
	>
		<div class="flex min-w-0 items-center gap-3">
			<ProviderAvatar
				:provider="details?.region_details.provider"
				:size="40"
				class="shrink-0"
			/>

			<div class="min-w-0 space-y-2">
				<div class="flex min-w-0 items-center gap-2">
					<h1 class="truncate text-xl-semibold text-ink-gray-9">
						{{ server.title || server.resource_id }}
					</h1>

					<Badge
						:label="visual.label"
						:theme="visual.badgeTheme"
						:class="{ 'animate-pulse': visual.pulse }"
					/>
				</div>

				<ul
					class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-gray-5"
				>
					<li
						v-for="fact in facts"
						:key="fact.icon"
						class="flex items-center gap-1.5"
					>
						<span :class="fact.icon" class="size-3.5 shrink-0" />
						{{ fact.label }}
					</li>

					<li v-if="address" class="min-w-0">
						<button
							type="button"
							class="flex min-w-0 items-center gap-1.5 rounded-2 hover:text-ink-gray-8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
							:aria-label="`Copy address ${address}`"
							title="Copy address"
							@click="copy(address, 'Address')"
						>
							<span class="lucide-globe size-3.5 shrink-0" />
							<span class="truncate">{{ address }}</span>
						</button>
					</li>
				</ul>
			</div>
		</div>

		<div class="flex shrink-0 gap-2">
			<Dropdown :options="menu" align="end">
				<Button
					label="Actions"
					icon-right="lucide-chevron-down"
					:loading="busy"
				/>
			</Dropdown>

			<Button
				v-if="canOpen"
				variant="solid"
				:label="siteUrl ? 'Visit site' : 'Open Pilot'"
				icon-right="lucide-arrow-up-right"
				:disabled="!isRunning || isLocked"
				:loading="opening"
				@click="emit('open')"
			/>
		</div>
	</header>
</template>
