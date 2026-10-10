<script setup lang="ts">
import { Alert, Dialog, TextInput, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, successToast } from '@/lib/feedback'

interface Props {
	server: VirtualMachineRow
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ renamed: [] }>()

const { activeTeam } = useSession()
const title = ref('')

const renameCall = useCall<
	{ title: string },
	{ team: string; resource_id: string; title: string }
>({
	url: method(API.renameServer),
	method: 'POST',
	immediate: false,
})

watch(open, (isOpen) => {
	if (!isOpen) return

	title.value = props.server.title || ''
	renameCall.reset()
})

const canSave = computed(() => {
	const next = title.value.trim()
	return !!next && next !== props.server.title && !!activeTeam.value
})

const error = computed(() =>
	renameCall.error
		? getErrorMessage(renameCall.error, "Couldn't rename the server.")
		: '',
)

async function save(): Promise<void> {
	if (!canSave.value || !activeTeam.value) return

	await renameCall.submit({
		team: activeTeam.value,
		resource_id: props.server.resource_id,
		title: title.value.trim(),
	})
	if (renameCall.error) return

	successToast('Server renamed')
	open.value = false
	emit('renamed')
}
</script>

<template>
	<Dialog
		v-model="open"
		title="Rename server"
		:actions="[
			{
				label: 'Save',
				variant: 'solid',
				loading: renameCall.loading,
				disabled: !canSave,
				onClick: save,
			},
		]"
	>
		<template #default>
			<div class="space-y-4">
				<Alert v-if="error" theme="red" :title="error" />

				<TextInput
					v-model="title"
					label="Name"
					maxlength="140"
					autofocus
					@keyup.enter="save"
				/>
			</div>
		</template>
	</Dialog>
</template>
