<script setup lang="ts">
import { computed } from 'vue'
import { Button, Dropdown, type DropdownOptions } from 'frappe-ui'
import type { InvitationRow } from '@/types/api'

const props = defineProps<{
	invitation: InvitationRow
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	resend: [invitation: InvitationRow]
	revoke: [invitation: InvitationRow]
}>()

const options = computed<DropdownOptions>(() => {
	if (!props.canManage || props.invitation.status !== 'Pending') return []

	return [
		{
			label: 'Resend',
			icon: 'lucide-send',
			onClick: () => emit('resend', props.invitation),
		},
		{
			label: 'Revoke',
			icon: 'lucide-ban',
			theme: 'red',
			onClick: () => emit('revoke', props.invitation),
		},
	]
})
</script>

<template>
	<Dropdown v-if="options.length" :options="options" placement="right">
		<template #trigger>
			<Button
				variant="ghost"
				icon="lucide-ellipsis-vertical"
				:loading="busy"
				aria-label="Invitation actions"
				@click.stop
			/>
		</template>
	</Dropdown>
</template>
