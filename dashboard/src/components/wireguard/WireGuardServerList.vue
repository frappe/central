<script setup lang="ts">
import { Badge, Button } from 'frappe-ui'
import CopyableValue from '@/components/common/CopyableValue.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import type { WireGuardServer } from '@/types/wireguard'

interface Props {
	servers: WireGuardServer[]
}

defineProps<Props>()
const { canManageNetwork } = useCapabilities()
</script>

<template>
	<div class="space-y-2">
		<p class="text-base-medium text-ink-gray-8">Servers in this region</p>
		<p v-if="!servers.length" class="text-p-sm text-ink-gray-5">
			No servers yet. A new server is reachable once you turn on its WireGuard
			access.
		</p>
		<ul v-else class="divide-y divide-outline-gray-1">
			<li
				v-for="server in servers"
				:key="server.resource_id"
				class="flex items-center justify-between gap-3 py-2"
			>
				<div class="min-w-0 space-y-1">
					<p class="truncate text-base text-ink-gray-8">{{ server.title }}</p>
					<CopyableValue
						v-if="server.ipv6_address"
						:value="server.ipv6_address"
						label="Private address"
					/>
				</div>
				<Badge
					v-if="server.has_wireguard_access"
					theme="green"
					label="Reachable"
				/>
				<Badge v-else-if="!canManageNetwork" theme="gray" label="Access off" />
				<Button
					v-else
					size="sm"
					label="Turn on access"
					:route="`/servers/${server.resource_id}/networking`"
				/>
			</li>
		</ul>
	</div>
</template>
