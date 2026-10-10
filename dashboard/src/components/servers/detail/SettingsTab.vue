<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import { isSettingUp } from '@/lib/status'

interface Props {
	server: VirtualMachineRow
	actions: ServerActions
}

const props = defineProps<Props>()

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
			description="Change CPU, memory or disk. Changing CPU or memory restarts the server. A disk can grow but never shrink."
		>
			<template v-if="actions.resize" #actions>
				<Button label="Resize" :disabled="isLocked" @click="emit('resize')" />
			</template>
		</SettingsSection>

		<SettingsSection
			v-if="actions.terminate"
			title="Terminate server"
			description="Destroys the server and its disk for good. Take a snapshot first to keep a copy."
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
