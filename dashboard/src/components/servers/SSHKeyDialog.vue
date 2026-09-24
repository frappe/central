<script setup lang="ts">
import { Alert, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { getErrorMessage } from '@/lib/feedback'
import { sshKeysProblem } from '@/lib/sshKeys'
import type { TeamSSHKey } from '@/types/sshKeys'

interface Props {
	modelValue: boolean
	keyToRotate?: TeamSSHKey | null
	save: (title: string, publicKey: string) => Promise<TeamSSHKey | void>
}

const props = defineProps<Props>()
const emit = defineEmits<{
	'update:modelValue': [value: boolean]
	saved: [key: TeamSSHKey | null]
}>()

const open = computed({
	get: () => props.modelValue,
	set: (value: boolean) => emit('update:modelValue', value),
})
const title = ref('')
const publicKey = ref('')
const busy = ref(false)
const error = ref('')
const problem = computed(() => sshKeysProblem(publicKey.value))

watch(open, (value) => {
	if (!value) return
	title.value = props.keyToRotate?.title ?? ''
	publicKey.value = ''
	error.value = ''
})

async function submit() {
	if (
		busy.value ||
		!title.value.trim() ||
		!publicKey.value.trim() ||
		problem.value
	)
		return
	busy.value = true
	error.value = ''
	try {
		const key = await props.save(title.value.trim(), publicKey.value.trim())
		emit('saved', key ?? null)
		open.value = false
	} catch (failure) {
		error.value = getErrorMessage(failure, "The SSH key couldn't be saved.")
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="keyToRotate ? 'Rotate SSH key' : 'Add SSH key'"
		size="lg"
	>
		<div class="flex flex-col gap-5">
			<p class="text-p-sm text-ink-gray-6">
				{{ keyToRotate
					? 'The new public key will replace this key on servers that selected it.'
					: 'Save a public key for your team, then select it when you create a server.' }}
			</p>
			<Alert v-if="error" theme="red" :title="error" />
			<FormControl
				v-if="!keyToRotate"
				v-model="title"
				label="Name"
				placeholder="Work laptop"
			/>
			<FormControl
				v-model="publicKey"
				type="textarea"
				label="SSH public key"
				placeholder="ssh-ed25519 AAAA…"
				:aria-invalid="!!problem"
			/>
			<p v-if="problem" class="text-p-sm text-ink-red-6">{{ problem }}</p>
			<p v-else class="text-p-sm text-ink-gray-5">
				Paste one line from a .pub file. Private keys are never needed.
			</p>
			<div class="flex justify-end gap-2">
				<Button label="Cancel" :disabled="busy" @click="open = false" />
				<Button
					:label="keyToRotate ? 'Rotate key' : 'Add key'"
					variant="solid"
					:loading="busy"
					:disabled="!title.trim() || !publicKey.trim() || !!problem"
					@click="submit"
				/>
			</div>
		</div>
	</Dialog>
</template>
