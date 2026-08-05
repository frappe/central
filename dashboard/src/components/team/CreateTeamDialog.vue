<script setup lang="ts">
import { Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useTeamSettings } from '@/composables/useTeamSettings'

// Create a new team. The caller becomes its Owner; on success the app switches to
// the new team (handled in useTeamSettings).
const open = defineModel<boolean>('open', { default: false })

const { saving, createTeam } = useTeamSettings()

const teamName = ref('')
watch(open, (isOpen) => {
	if (isOpen) teamName.value = ''
})

const canSubmit = computed(() => teamName.value.trim().length > 0)

const submit = async () => {
	if (!canSubmit.value) return
	if (await createTeam(teamName.value.trim())) open.value = false
}

const dialogOptions = computed(() => ({
	title: 'Create a team',
	actions: [
		{
			label: 'Create team',
			variant: 'solid' as const,
			loading: saving.value,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<FormControl
				v-model="teamName"
				label="Team name"
				placeholder="e.g. Acme Production"
				@keyup.enter="submit"
			/>
		</template>
	</Dialog>
</template>
