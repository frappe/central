<script setup lang="ts">
import { Alert, Button } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { useServerRescue } from '@/composables/useServerRescue'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import { canStart, isSettingUp } from '@/lib/status'

interface Props {
	server: VirtualMachineRow
	actions: ServerActions
}

const props = defineProps<Props>()
const { state, loading, saving, error, refresh, select } = useServerRescue(
	computed(() => props.server.resource_id),
)
const selection = ref<boolean | null>(null)
const canSelect = computed(
	() =>
		props.actions.power &&
		props.actions.console &&
		!props.actions.isAccessLocked,
)
const rescueButtonLabel = computed(() => {
	const isEnabled = state.value?.is_rescue_mode_enabled
	if (isEnabled == null) return loading.value ? 'Enable' : 'N/A'
	return isEnabled ? 'Disable' : 'Enable'
})
const bootAction = computed(() =>
	canStart(props.server.status) ? 'Start' : 'Restart',
)
const pendingBootMessage = computed(() => {
	const rescue = state.value
	if (
		rescue?.is_rescue_mode_enabled == null ||
		rescue.is_in_rescue_mode == null
	)
		return ''
	if (rescue.is_rescue_mode_enabled === rescue.is_in_rescue_mode) return ''
	return rescue.is_rescue_mode_enabled
		? `${bootAction.value} the server to boot into rescue mode.`
		: `${bootAction.value} the server to boot normally.`
})
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
			title="Resize server"
			description="Change CPU, memory, or disk size. CPU and memory changes restart the server. Disk size can only increase."
		>
			<template v-if="actions.resize" #actions>
				<Button label="Resize" :disabled="isLocked" @click="emit('resize')" />
			</template>
		</SettingsSection>

		<SettingsSection
			title="Rescue mode"
			description="Boot a rescue environment with your original disk attached."
		>
			<Alert
				v-if="pendingBootMessage"
				theme="amber"
				:title="pendingBootMessage"
			/>
			<p v-if="error" role="alert" class="text-p-sm text-ink-red-5">
				{{ error }}
			</p>
			<template #actions>
				<Button
					v-if="canSelect"
					:label="rescueButtonLabel"
					:disabled="isLocked || loading || saving || state?.is_rescue_mode_enabled == null"
					@click="selection = !state?.is_rescue_mode_enabled"
				/>
			</template>
		</SettingsSection>
		<ConfirmDialog
			v-model:target="selection"
			:title="selection ? 'Enable rescue mode' : 'Disable rescue mode'"
			:confirm-label="selection ? 'Enable' : 'Disable'"
			size="lg"
			:loading="saving"
			:error="error"
			:disabled="state?.is_rescue_mode_enabled == null"
			@confirm="confirmSelection"
		>
			<div v-if="selection" class="space-y-3 text-p-base text-ink-gray-7">
				<p>
					The server boots into rescue mode the next time you start or restart
					it. This does not restart the server now.
				</p>
				<p>
					Your original disk is attached in rescue mode. Changes you make apply
					to that disk, so it's safer to take a snapshot first.
				</p>
				<p class="font-semibold text-ink-gray-8">
					{{ bootAction }}
					the server after you enable rescue mode.
				</p>
			</div>
			<div v-else class="space-y-3 text-p-base text-ink-gray-7">
				<p>
					The server boots normally the next time you start or restart it. This
					does not restart the server now.
				</p>
				<p class="font-semibold text-ink-gray-8">
					{{ bootAction }}
					the server after you disable rescue mode.
				</p>
			</div>
		</ConfirmDialog>

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
