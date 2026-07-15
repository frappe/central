<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Dialog, FormControl } from 'frappe-ui'
import { useTeamSettings } from '@/composables/useTeamSettings'

// Create a new team. The caller becomes its Owner; on success the app switches to
// the new team (handled in useTeamSettings).
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [v: boolean] }>()

const { saving, createTeam } = useTeamSettings()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

const teamName = ref('')
watch(open, (isOpen) => {
	if (isOpen) teamName.value = ''
})

const canSubmit = computed(() => teamName.value.trim().length > 0)

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

async function submit() {
	if (!canSubmit.value) return
	if (await createTeam(teamName.value.trim())) open.value = false
}
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
