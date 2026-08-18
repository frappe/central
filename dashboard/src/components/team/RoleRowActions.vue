<script setup lang="ts">
import { type DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { TeamRoleRow } from '@/types/api'

const props = defineProps<{
	role: TeamRoleRow
	canManage: boolean
	busy?: boolean
}>()

const emit = defineEmits<{ delete: [role: TeamRoleRow] }>()

const options = computed<DropdownOptions>(() => {
	if (!props.canManage || props.role.is_system) return []

	return [
		{
			label: 'Delete',
			icon: 'lucide-trash-2',
			theme: 'red',
			onClick: () => emit('delete', props.role),
		},
	]
})
</script>

<template>
	<RowActionsMenu :options="options" label="Role actions" :busy="busy" />
</template>
