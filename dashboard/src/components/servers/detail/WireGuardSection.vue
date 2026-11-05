<script setup lang="ts">
import { Switch } from 'frappe-ui'
import { computed } from 'vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerWireGuardAccess } from '@/composables/useServerWireGuardAccess'
import { openSettings } from '@/composables/useSettings'
import { successToast } from '@/lib/feedback'

interface Props {
	resourceId: string
	hasAccess: boolean
	/** The firewall is on and no rule lets a WireGuard VPN device in. */
	isBlockedByFirewall: boolean
	/** The viewer holds server:network on this server. */
	canManageNetwork: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: [] }>()

const { canManageWireGuard } = useCapabilities()
const { setWireGuardAccess, isSavingAccess } = useServerWireGuardAccess(
	computed(() => props.resourceId),
)

async function toggle(enabled: boolean): Promise<void> {
	if (!(await setWireGuardAccess(enabled))) return

	successToast(enabled ? 'WireGuard VPN is on' : 'WireGuard VPN is off')
	emit('changed')
}
</script>

<template>
	<SettingsSection title="WireGuard VPN">
		<template #description>
			Let your team's WireGuard VPN devices reach this server at its private
			address.
			<button
				v-if="canManageWireGuard"
				type="button"
				class="text-p-sm-medium text-ink-gray-8 underline"
				@click="openSettings('wireguard')"
			>
				Manage devices
			</button>
		</template>

		<p
			v-if="hasAccess && isBlockedByFirewall"
			class="flex items-start gap-1.5 text-p-sm text-ink-amber-7"
		>
			<span
				class="lucide-triangle-alert mt-0.5 size-4 shrink-0"
				aria-hidden="true"
			/>
			<span>
				The firewall blocks every WireGuard VPN device.
				<RouterLink
					:to="`/servers/${resourceId}/networking`"
					class="text-p-sm-medium underline"
					>Allow devices in the firewall</RouterLink
				>
			</span>
		</p>

		<template #actions>
			<Switch
				:model-value="hasAccess"
				:disabled="!canManageNetwork || isSavingAccess"
				@update:model-value="toggle"
			>
				<template #label><span class="sr-only">WireGuard VPN</span></template>
			</Switch>
		</template>
	</SettingsSection>
</template>
