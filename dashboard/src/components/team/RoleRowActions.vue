<script setup lang="ts">
import { Button, Dropdown, type DropdownOptions } from 'frappe-ui'
import { computed } from 'vue'
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
	<Dropdown v-if="options.length" :options="options" placement="right">
		<template #trigger>
			<Button
				variant="ghost"
				icon="lucide-ellipsis-vertical"
				:loading="busy"
				aria-label="Role actions"
				@click.stop
			/>
		</template>
	</Dropdown>
</template>
