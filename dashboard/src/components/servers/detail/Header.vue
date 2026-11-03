<script setup lang="ts">
import { Badge, Button, Dropdown, Tooltip } from 'frappe-ui'
import { computed } from 'vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import type {
	ConsoleMode,
	ServerCommand,
	VirtualMachineRow,
} from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import { formatCalendarDate, timeAgo } from '@/lib/datetime'
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
	isSavingProtection: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
	open: []
	pilot: []
	command: [command: Exclude<ServerCommand, 'terminate'>]
	console: [mode: ConsoleMode]
	rename: []
	snapshot: []
	resize: []
	terminate: []
	protect: [enabled: boolean]
}>()

const visual = computed(() => statusVisual(props.server))
const isLocked = computed(() => !!props.server.pending_action)
const isRunning = computed(() => props.server.status === 'Running')
const isUbuntu = computed(() => props.server.image_offering === 'ubuntu')

const isProtected = computed(() => !!props.details?.is_termination_protected)
const protectionLabel = computed(() =>
	isProtected.value
		? 'Turn off termination protection'
		: 'Turn on termination protection',
)

interface Fact {
	icon: string
	label: string | null
	help?: string
}

const createdFact = computed<Fact | null>(() => {
	const details = props.details
	if (!details) return null

	const creator = details.created_by_name || details.created_by
	return {
		icon: 'lucide-clock',
		label: creator
			? `Created ${timeAgo(details.creation)} by ${creator}`
			: `Created ${timeAgo(details.creation)}`,
		help: [formatCalendarDate(details.creation), details.created_by]
			.filter(Boolean)
			.join(' · '),
	}
})

const facts = computed<Fact[]>(() => {
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
			label: isUbuntu.value ? 'Ubuntu' : null,
		},
		{
			icon: 'lucide-package',
			label:
				details &&
				formatPlanLabel({
					title: details.plan_title,
					vcpus: details.vcpus,
					memoryMegabytes: details.memory_megabytes,
					rate: details.plan_rate,
					currency: details.plan_currency,
					billingCycle: details.plan_billing_cycle,
				}),
		},
		createdFact.value,
	].filter((fact): fact is Fact => !!fact?.label)
})

const canOpen = computed(
	() =>
		props.actions.open &&
		!isUbuntu.value &&
		!isSettingUp(props.server.status) &&
		// Without a site, Open signs in to Pilot, which a free trial locks.
		(!!props.siteUrl ||
			(!!props.server.gateway_url && !props.actions.isAccessLocked)),
)

const handlers: Partial<Record<ServerMenuVerb, () => void>> = {
	open: () => emit('open'),
	pilot: () => emit('pilot'),
	start: () => emit('command', 'start'),
	stop: () => emit('command', 'stop'),
	restart: () => emit('command', 'restart'),
	resize: () => emit('resize'),
	snapshot: () => emit('snapshot'),
	'ssh-console': () => emit('console', 'ssh'),
	'tty-console': () => emit('console', 'tty'),
	rename: () => emit('rename'),
	terminate: () => emit('terminate'),
}

const operatorItems = computed(() => {
	const links = props.details?.operator_links
	if (!links) return []

	const { desk_url: deskUrl, atlas_url: atlasUrl } = links
	const open = (url: string) => window.open(url, '_blank', 'noopener')
	return [
		{
			label: 'Open in Desk',
			icon: 'lucide-app-window',
			onClick: () => open(deskUrl),
		},
		...(atlasUrl
			? [
					{
						label: 'Open in Atlas',
						icon: 'lucide-earth',
						onClick: () => open(atlasUrl),
					},
				]
			: []),
	]
})

const menu = computed(() => {
	const groups = getServerMenu(
		props.server,
		props.actions,
		(verb) => handlers[verb]?.(),
		{
			site: props.siteUrl ? new URL(props.siteUrl).host : null,
			isOnServerPage: true,
		},
	)
	if (!operatorItems.value.length) return groups

	return [
		...groups,
		{ group: 'Operator', hideLabel: true, options: operatorItems.value },
	]
})
</script>

<template>
	<header
		class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
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
						:class="{ 'animate-pulse': visual.motion !== 'none' }"
					/>

					<Tooltip
						v-if="details?.has_wireguard_access"
						text="Your team's WireGuard VPN devices reach this server at its private address."
					>
						<RouterLink
							:to="`/servers/${server.resource_id}/access`"
							class="shrink-0 rounded-full focus-visible:ring-2 focus-visible:ring-outline-gray-3"
						>
							<Badge label="VPN" theme="blue">
								<template #prefix>
									<span class="lucide-shield-check size-3" aria-hidden="true" />
								</template>
							</Badge>
						</RouterLink>
					</Tooltip>
				</div>

				<ul
					class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-gray-5"
				>
					<li v-for="fact in facts" :key="fact.icon">
						<Tooltip :text="fact.help">
							<span class="flex items-center gap-1.5">
								<span :class="fact.icon" class="size-3.5 shrink-0" />
								{{ fact.label }}
							</span>
						</Tooltip>
					</li>
				</ul>
			</div>
		</div>

		<div class="flex shrink-0 gap-2">
			<Button
				v-if="details && actions.terminate && !actions.isAccessLocked"
				variant="ghost"
				:icon="isProtected ? 'lucide-lock' : 'lucide-lock-open'"
				:label="protectionLabel"
				:tooltip="protectionLabel"
				:loading="isSavingProtection"
				@click="emit('protect', !isProtected)"
			/>

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
