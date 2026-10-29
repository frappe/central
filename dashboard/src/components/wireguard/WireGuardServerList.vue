<script setup lang="ts">
import { TextInput } from 'frappe-ui'
import { computed, ref } from 'vue'
import WireGuardServerRow from '@/components/wireguard/WireGuardServerRow.vue'
import type { WireGuardRegion, WireGuardServer } from '@/types/wireguard'

interface Props {
	regions: WireGuardRegion[]
	servers: WireGuardServer[]
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: [] }>()

const query = ref('')
const isSearchable = computed(() => props.servers.length > 6)
const matches = (server: WireGuardServer): boolean => {
	const text = query.value.trim().toLowerCase()
	return [server.title, server.ipv6_address ?? '']
		.join(' ')
		.toLowerCase()
		.includes(text)
}

// A device reaches only its own region, so the servers group by region.
const groups = computed(() =>
	props.regions
		.map((region) => ({
			name: region.name,
			label: region.display_name || region.name,
			servers: props.servers.filter(
				(server) => server.region === region.name && matches(server),
			),
		}))
		.filter((group) => group.servers.length),
)
</script>

<template>
	<TextInput
		v-if="isSearchable"
		v-model="query"
		type="search"
		placeholder="Search servers"
		aria-label="Search servers"
	>
		<template #prefix>
			<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
		</template>
	</TextInput>

	<p
		v-if="!groups.length && query.trim()"
		class="py-4 text-p-sm text-ink-gray-6"
	>
		No server matches “{{ query.trim() }}”.
		<button
			type="button"
			class="text-p-sm-medium text-ink-gray-8 underline"
			@click="query = ''"
		>
			Clear search
		</button>
	</p>
	<p v-else-if="!groups.length" class="text-p-sm text-ink-gray-5">
		No servers in a WireGuard VPN region yet.
	</p>

	<section v-for="group in groups" v-else :key="group.name">
		<h3 v-if="regions.length > 1" class="text-sm-medium text-ink-gray-6">
			{{ group.label }}
		</h3>
		<ul class="divide-y divide-outline-gray-1">
			<WireGuardServerRow
				v-for="server in group.servers"
				:key="server.resource_id"
				:server="server"
				@changed="emit('changed')"
			/>
		</ul>
	</section>
</template>
