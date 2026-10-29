<script setup lang="ts">
import { Button, Switch } from 'frappe-ui'
import { computed } from 'vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerWireGuardAccess } from '@/composables/useServerWireGuardAccess'
import { openSettings } from '@/composables/useSettings'
import { successToast } from '@/lib/feedback'

interface Props {
	resourceId: string
	hasAccess: boolean
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

	successToast(enabled ? 'WireGuard access is on' : 'WireGuard access is off')
	emit('changed')
}
</script>

<template>
	<SettingsSection
		title="WireGuard"
		description="Devices that reach this server over the regional gateway."
	>
		<template v-if="canManageWireGuard" #actions>
			<Button
				icon-left="lucide-shield"
				label="Manage devices"
				@click="openSettings('wireguard')"
			/>
		</template>

		<Switch
			:model-value="hasAccess"
			:disabled="!canManageNetwork || isSavingAccess"
			label="WireGuard access"
			:description="
				hasAccess
					? 'WireGuard devices of your team reach this server at its private IPv6 address.'
					: 'Lets WireGuard devices of your team reach the private address of this server.'
			"
			class="rounded-6 px-2 py-3"
			@update:model-value="toggle"
		/>
	</SettingsSection>
</template>
