<script setup lang="ts">
import { Select, Skeleton } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useServerMapData } from '@/composables/useServerMapData'
import type {
	SupportCategoryKey,
	SupportContext,
	SupportServer,
} from '@/composables/useSupport'
import { getServerReference, getSupportServer } from '@/composables/useSupport'

interface Props {
	context: SupportContext
	category: SupportCategoryKey | ''
}

const props = defineProps<Props>()
const emit = defineEmits<{
	selection: [value: { server: SupportServer | null; site: string }]
}>()
const serverId = defineModel<string>('serverId', { required: true })
const siteName = defineModel<string>('siteName', { required: true })

const { servers, sites, loaded } = useServerMapData()

const contextServer = computed(() => getSupportServer(props.context))

/** The fleet, plus the server a surface named when the fleet has not loaded yet. */
const serverOptions = computed(() => {
	const options = servers.value.map((server) => ({
		value: server.resource_id,
		label: getServerReference(server),
	}))
	const named = contextServer.value
	if (named && !options.some((option) => option.value === named.resource_id))
		options.push({
			value: named.resource_id,
			label: getServerReference(named),
		})
	return options
})

/** Only the selected server's sites, so the ticket names a machine the team owns. */
const siteOptions = computed(() => {
	const serverName =
		servers.value.find((server) => server.resource_id === serverId.value)
			?.name ?? contextServer.value?.name
	return sites.value
		.filter((site) => !serverName || site.server === serverName)
		.map((site) => ({
			value: site.name,
			label: site.subdomain ? `${site.subdomain} (${site.name})` : site.name,
		}))
})

const selectedServer = computed(
	() =>
		servers.value.find((server) => server.resource_id === serverId.value) ??
		contextServer.value,
)

const selectedSite = computed(
	() =>
		siteOptions.value.find((option) => option.value === siteName.value) ?? null,
)

// A new server leaves the previously picked site out of the filtered list.
watch(serverId, () => {
	if (
		siteName.value &&
		!siteOptions.value.some((o) => o.value === siteName.value)
	)
		siteName.value = ''
})

// The fleet loads after the dialog opens, so the context fills in when it lands.
watch(
	loaded,
	(isLoaded) => {
		if (!isLoaded) return
		serverId.value ||= matchingServer(props.context.Server)
		siteName.value ||= matchingSite(props.context.Site)
	},
	{ immediate: true },
)

reset()

// The read-only summary beside the form mirrors what the ticket will carry.
watch(
	[selectedServer, selectedSite],
	() =>
		emit('selection', {
			server: selectedServer.value ?? null,
			site: selectedSite.value?.label ?? '',
		}),
	{ immediate: true },
)

function reset(): void {
	serverId.value =
		getSupportServer(props.context)?.resource_id ??
		matchingServer(props.context.Server)
	siteName.value = matchingSite(props.context.Site)
}

function matchingServer(reference: SupportContext[string]): string {
	if (typeof reference !== 'string' || !reference) return ''
	const server = servers.value.find(
		(candidate) =>
			candidate.resource_id === reference ||
			`${candidate.title} (${candidate.resource_id})` === reference,
	)
	return server?.resource_id ?? ''
}

function matchingSite(address: SupportContext[string]): string {
	if (typeof address !== 'string' || !address) return ''
	const site = sites.value.find(
		(candidate) =>
			candidate.name === address || candidate.subdomain === address,
	)
	return site?.name ?? ''
}

defineExpose({ reset })
</script>

<template>
	<div v-if="category === 'server' || category === 'site'" class="space-y-2">
		<div v-if="!loaded" class="grid grid-cols-2 gap-3" aria-busy="true">
			<Skeleton class="h-9 rounded-4" />
			<Skeleton class="h-9 rounded-4" />
		</div>
		<p v-else-if="!serverOptions.length" class="text-p-sm text-ink-gray-5">
			This team has no servers yet.
		</p>
		<div
			v-else
			class="grid gap-3"
			:class="siteOptions.length ? 'grid-cols-2' : 'grid-cols-1'"
		>
			<Select
				v-model="serverId"
				label="Server"
				:options="serverOptions"
				placeholder="Not about one server"
				side="bottom"
			/>
			<Select
				v-if="siteOptions.length"
				v-model="siteName"
				label="Site"
				:options="siteOptions"
				placeholder="Not about one site"
				side="bottom"
			/>
		</div>
	</div>
</template>
