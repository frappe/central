<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { useServerRescue } from '@/composables/useServerRescue'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import { isSettingUp } from '@/lib/status'

interface Props {
	server: VirtualMachineRow
	actions: ServerActions
}

const props = defineProps<Props>()
const { state, loading, saving, error, notice, refresh, select } =
	useServerRescue(computed(() => props.server.resource_id))
const selection = ref<boolean | null>(null)
const canSelect = computed(
	() =>
		props.actions.power &&
		props.actions.console &&
		!props.actions.isAccessLocked,
)
const bootLabel = (value: boolean | null | undefined) =>
	value == null ? 'Unknown' : value ? 'Rescue' : 'Normal'
async function confirmSelection(enabled: boolean) {
	if (await select(enabled)) selection.value = null
}
watch(
	() => props.server.pending_action,
	() => {
		if (!saving.value) refresh()
	},
)
watch(
	() => props.server.resource_id,
	() => {
		selection.value = null
	},
)

const emit = defineEmits<{
	resize: []
	terminate: []
}>()

const isLocked = computed(
	() => !!props.server.pending_action || isSettingUp(props.server.status),
)
</script>

<template>
	<div class="divide-y divide-outline-gray-1">
		<SettingsSection
			title="Rescue mode"
			description="Boot a repair environment with your original disk attached. Repairs change that disk. Take a snapshot before repairing."
		>
			<p class="text-p-sm text-ink-gray-7">
				Last boot: {{ bootLabel(state?.is_in_rescue_mode) }}. Next boot:
				{{ bootLabel(state?.is_rescue_mode_enabled) }}.
			</p>
			<p
				v-if="state?.is_rescue_mode_enabled !== null && state?.is_in_rescue_mode !== null && state && state.is_rescue_mode_enabled !== state.is_in_rescue_mode"
				class="text-p-sm text-ink-gray-7"
			>
				{{ server.status === 'Stopped' ? 'Start the server to apply this selection.' : 'Restart the server to apply this selection.' }}
				Refresh status after it boots.
			</p>
			<p v-if="notice" class="text-p-sm text-ink-gray-7">{{ notice }}</p>
			<p v-if="error" role="alert" class="text-p-sm text-ink-red-5">
				{{ error }}
			</p>
			<template #actions>
				<Button
					label="Refresh status"
					:loading="loading"
					:disabled="saving"
					@click="refresh"
				/>
				<Button
					v-if="canSelect"
					:label="state?.is_rescue_mode_enabled ? 'Disable rescue' : 'Enable rescue'"
					:disabled="isLocked || loading || saving || state?.is_rescue_mode_enabled == null"
					@click="selection = !state?.is_rescue_mode_enabled"
				/>
			</template>
		</SettingsSection>
		<ConfirmDialog
			v-model:target="selection"
			:title="selection ? 'Enable rescue mode' : 'Disable rescue mode'"
			confirm-label="Change boot selection"
			:loading="saving"
			:error="error"
			:disabled="state?.is_rescue_mode_enabled == null"
			@confirm="confirmSelection"
		>
			<p class="text-p-base text-ink-gray-7">
				This changes how the server boots the next time you start or restart it.
				It does not restart the server now. Enabling rescue can wake a sleeping
				server.
			</p>
		</ConfirmDialog>
		<SettingsSection
			title="Resize server"
			description="Change CPU, memory, or disk size. CPU and memory changes restart the server. Disk size can only increase."
		>
			<template v-if="actions.resize" #actions>
				<Button label="Resize" :disabled="isLocked" @click="emit('resize')" />
			</template>
		</SettingsSection>

		<SettingsSection
			v-if="actions.terminate"
			title="Terminate server"
			description="Permanently deletes the server and its disk. Create a snapshot first to keep a backup."
		>
			<template #actions>
				<Button
					theme="red"
					label="Terminate"
					:disabled="isLocked"
					@click="emit('terminate')"
				/>
			</template>
		</SettingsSection>
	</div>
</template>
