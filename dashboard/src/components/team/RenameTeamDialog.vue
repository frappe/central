<script setup lang="ts">
import { Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [open: boolean] }>()

const { activeTeamLabel } = useSession()
const { saving, rename } = useTeamSettings()

const open = computed({
	get: () => props.open,
	set: (value: boolean) => emit('update:open', value),
})

const name = ref(activeTeamLabel.value)
watch(open, (isOpen) => {
	if (isOpen) name.value = activeTeamLabel.value
})

const changed = computed(
	() => !!name.value.trim() && name.value.trim() !== activeTeamLabel.value,
)

async function submit(): Promise<void> {
	if (!changed.value) return
	if (await rename(name.value.trim())) open.value = false
}

const dialogOptions = computed(() => ({
	title: 'Rename team',
	actions: [
		{
			label: 'Save',
			variant: 'solid' as const,
			loading: saving.value,
			disabled: !changed.value,
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
				v-model="name"
				label="Team name"
				placeholder="Acme"
				autocomplete="off"
			/>
		</template>
	</Dialog>
</template>
