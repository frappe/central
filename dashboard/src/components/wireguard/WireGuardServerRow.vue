<script setup lang="ts">
import { Switch } from 'frappe-ui'
import { computed } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerWireGuardAccess } from '@/composables/useServerWireGuardAccess'
import { successToast } from '@/lib/feedback'
import type { WireGuardServer } from '@/types/wireguard'

interface Props {
	server: WireGuardServer
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: [] }>()

const { canManageNetwork } = useCapabilities()
const { setWireGuardAccess, isSavingAccess } = useServerWireGuardAccess(
	computed(() => props.server.resource_id),
)

async function toggle(enabled: boolean): Promise<void> {
	if (!(await setWireGuardAccess(enabled))) return

	successToast(
		`WireGuard VPN is ${enabled ? 'on' : 'off'} for ${props.server.title}`,
	)
	emit('changed')
}
</script>

<template>
	<li class="flex items-center justify-between gap-3 py-2.5">
		<div class="min-w-0 space-y-1">
			<p class="truncate text-base text-ink-gray-8" :title="server.title">
				{{ server.title }}
			</p>
			<CopyableValue
				v-if="server.ipv6_address"
				:value="
					server.has_wireguard_access
						? `ssh root@${server.ipv6_address}`
						: server.ipv6_address
				"
				:label="server.has_wireguard_access ? 'SSH command' : 'Private address'"
			/>
		</div>

		<Switch
			:model-value="!!server.has_wireguard_access"
			:disabled="!canManageNetwork || isSavingAccess"
			@update:model-value="toggle"
		>
			<template #label>
				<span class="sr-only">WireGuard VPN for {{ server.title }}</span>
			</template>
		</Switch>
	</li>
</template>
