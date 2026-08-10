<script setup lang="ts">
import { Badge, Button, Dialog, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import ListViewState from '@/components/common/list-view/ListViewState.vue'
import LoadAverageCard from '@/components/servers/overview/LoadAverageCard.vue'
import OverviewSkeleton from '@/components/servers/overview/OverviewSkeleton.vue'
import ResourceUsageCard from '@/components/servers/overview/ResourceUsageCard.vue'
import ServerInfoCard from '@/components/servers/overview/ServerInfoCard.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import { useRegions } from '@/composables/useRegions'
import type { AssetRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import type { LoadPoint } from '@/lib/loadChart'
import { formatPlanLabel } from '@/lib/planLabel'
import { statusVisual } from '@/lib/serverMap'
import { getErrorMessage } from '@/lib/toast'

type Overview = {
	server: AssetRow & {
		creation: string
		plan_title: string | null
		plan_rate: number | null
		plan_currency: string | null
		plan_billing_cycle: string | null
		team_name: string
		region: { display_name?: string | null; provider?: string | null }
	}
	monitoring: {
		available: boolean
		current?: {
			cpu_percent?: number
			memory_used?: number
			memory_total?: number
			disk_used?: number
			disk_total?: number
		}
		history?: { system?: { points?: LoadPoint[] } }
	}
}

const props = defineProps<{
	server: AssetRow | null
	canOpen: boolean
	canResize?: boolean
}>()

const emit = defineEmits<{
	open: [server: AssetRow]
	resize: [server: AssetRow]
}>()

const open = defineModel<boolean>('open', { required: true })
const { activeTeam } = useSession()
const { regions } = useRegions()
const overview = ref<Overview | null>(null)
const hasLoaded = ref(false)
const overviewError = ref('')

const overviewCall = useCall<Overview, { team: string; resource_id: string }>({
	url: method(API.serverOverview),
	method: 'GET',
	immediate: false,
})

watch([open, () => props.server?.resource_id], ([isOpen, resourceId]) => {
	if (!isOpen) {
		overview.value = null
		overviewError.value = ''
		hasLoaded.value = false
		return
	}
	if (!resourceId || !activeTeam.value) return
	void load(resourceId)
})

async function load(resourceId: string): Promise<void> {
	overview.value = null
	overviewError.value = ''
	hasLoaded.value = false
	try {
		await overviewCall.submit({
			team: activeTeam.value!,
			resource_id: resourceId,
		})
		if (overviewCall.error) throw overviewCall.error
		overview.value = overviewCall.data ?? null
	} catch (error) {
		overviewError.value = getErrorMessage(
			error,
			"We couldn't load this server. Try again.",
		)
	} finally {
		hasLoaded.value = true
	}
}

function close(): void {
	open.value = false
}

function openServer(): void {
	if (!props.server) return
	close()
	emit('open', props.server)
}

function expandStorage(): void {
	if (!props.server) return
	close()
	emit('resize', props.server)
}

const server = computed(() => overview.value?.server)
const current = computed(() => overview.value?.monitoring.current)
const loadPoints = computed(
	() => overview.value?.monitoring.history?.system?.points ?? [],
)
const visual = computed(() => {
	const row = server.value ?? props.server
	return row ? statusVisual(row) : null
})
const provider = computed(() => {
	if (server.value?.region.provider) return server.value.region.provider
	const cluster = props.server?.cluster
	if (!cluster) return null
	return (
		regions.value.find((region) => region.region === cluster)?.provider || null
	)
})
const locationLine = computed(() => {
	if (server.value) {
		const location = server.value.region.display_name || server.value.cluster
		const name = server.value.region.provider
		return name ? `${location} · ${name}` : location
	}
	const cluster = props.server?.cluster
	if (!cluster) return ''
	const region = regions.value.find((entry) => entry.region === cluster)
	const location = region?.display_name || cluster
	return region?.provider ? `${location} · ${region.provider}` : location
})
const title = computed(
	() =>
		props.server?.title ||
		props.server?.resource_id ||
		server.value?.title ||
		'Server overview',
)
const planLabel = computed(() =>
	formatPlanLabel({
		title: server.value?.plan_title,
		rate: server.value?.plan_rate,
		currency: server.value?.plan_currency,
		billingCycle: server.value?.plan_billing_cycle,
	}),
)
</script>

<template>
	<Dialog v-model:open="open" size="3xl" bare>
		<div class="bg-surface-elevation-1 px-6 pb-6 pt-5">
			<header class="mb-5 flex items-start justify-between gap-4">
				<div class="flex min-w-0 items-start gap-3">
					<ProviderAvatar :provider="provider" :size="40" />
					<div class="min-w-0">
						<div class="flex flex-wrap items-center gap-2">
							<Dialog.Title as-child>
								<h2
									class="truncate text-xl font-semibold leading-6 text-ink-gray-9"
								>
									{{ title }}
								</h2>
							</Dialog.Title>
							<Badge
								v-if="visual"
								:label="visual.label"
								:theme="visual.badgeTheme"
								variant="subtle"
								size="sm"
							/>
						</div>
						<p class="mt-0.5 truncate text-sm text-ink-gray-5">
							{{ locationLine || '—' }}
						</p>
					</div>
				</div>
				<Dialog.Close as-child>
					<Button variant="ghost" label="Close">
						<template #icon>
							<span class="lucide-x size-4 text-ink-gray-9" />
						</template>
					</Button>
				</Dialog.Close>
			</header>

			<OverviewSkeleton v-if="!hasLoaded" />

			<div v-else-if="overview && server" class="space-y-4">
				<ResourceUsageCard
					:available="overview.monitoring.available && !!current"
					:vcpus="server.vcpus"
					:cpu-percent="current?.cpu_percent"
					:memory-used="current?.memory_used"
					:memory-total="current?.memory_total"
					:disk-used="current?.disk_used"
					:disk-total="current?.disk_total"
					:can-expand-storage="canResize"
					@expand-storage="expandStorage"
				/>

				<div class="grid gap-4 md:grid-cols-2">
					<ServerInfoCard
						:hosted-on="server.region.display_name || server.cluster || '—'"
						:provider="server.region.provider"
						:plan="planLabel"
						:inbound-ip="server.public_ipv4 || '—'"
						:frappe-version="server.frappe_version || '—'"
						:created-on="server.creation"
						:owned-by="server.team_name"
					/>
					<LoadAverageCard :points="loadPoints" />
				</div>
			</div>

			<ListViewState
				v-else
				kind="error"
				title="Couldn't load this server"
				:description="overviewError"
				@retry="props.server && load(props.server.resource_id)"
			/>

			<footer class="mt-6 flex justify-end gap-2">
				<Button label="Close" @click="close" />
				<Button
					v-if="props.server && canOpen"
					variant="subtle"
					label="Open server"
					icon-right="lucide-arrow-up-right"
					@click="openServer"
				/>
			</footer>
		</div>
	</Dialog>
</template>
