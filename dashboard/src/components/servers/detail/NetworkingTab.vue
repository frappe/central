<script setup lang="ts">
import { Badge, Button, Skeleton } from 'frappe-ui'
import { computed } from 'vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import AddressesSection from '@/components/servers/detail/AddressesSection.vue'
import FirewallSection from '@/components/servers/firewall/FirewallSection.vue'
import { useServerHostnames } from '@/composables/useServerHostnames'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerOverview } from '@/types/servers'

interface Props {
	server: VirtualMachineRow
	overview: ServerOverview
	/** The viewer holds server:network on this server. */
	canManageNetwork: boolean
	/** The other servers of the team, for copying firewall rules. */
	servers: VirtualMachineRow[]
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: [] }>()

const { hostnames, loading, error } = useServerHostnames(
	computed(() => props.server),
)
</script>

<template>
	<div class="divide-y divide-outline-gray-1">
		<AddressesSection
			:server="overview.server"
			:can-edit="canManageNetwork"
			@changed="emit('changed')"
		/>

		<FirewallSection
			:resource-id="overview.server.resource_id"
			:region="overview.server.region"
			:is-enabled="!!overview.server.is_firewall_enabled"
			:rules="overview.server.firewall_rules"
			:can-edit="canManageNetwork"
			:servers="servers"
			@changed="emit('changed')"
		/>

		<SettingsSection
			title="Domains"
			help="Site and custom domains that point to this server."
		>
			<div v-if="loading" class="space-y-2" aria-busy="true">
				<Skeleton class="h-9 rounded-4" />
				<Skeleton class="h-9 w-2/3 rounded-4" />
			</div>

			<p v-else-if="error" class="text-p-sm text-ink-gray-5">{{ error }}</p>

			<p v-else-if="!hostnames.length" class="text-p-sm text-ink-gray-5">
				No site or custom domain points to this server.
			</p>

			<ul v-else class="divide-y divide-outline-gray-1">
				<li
					v-for="entry in hostnames"
					:key="entry.hostname"
					class="flex items-center gap-3 py-2 first:pt-0 last:pb-0"
				>
					<span
						class="lucide-globe size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>

					<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-8">
						{{ entry.hostname }}
					</span>

					<Badge :label="entry.kind" />

					<Button
						variant="ghost"
						icon="lucide-arrow-up-right"
						:label="`Open ${entry.hostname}`"
						tooltip="Open"
						:href="`https://${entry.hostname}`"
					/>
				</li>
			</ul>
		</SettingsSection>
	</div>
</template>
