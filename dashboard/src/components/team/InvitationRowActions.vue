<script setup lang="ts">
import { type DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
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
	<RowActionsMenu :options="options" label="Invitation actions" :busy="busy" />
</template>
