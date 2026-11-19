<script setup lang="ts">
import { TextInput } from 'frappe-ui'
import type { AppInput } from '@/types/serverCreation'

defineProps<{ inputs: AppInput[] }>()

const answers = defineModel<Record<string, string>>({ required: true })

const inputTypes: Record<AppInput['type'], string> = {
	string: 'text',
	domain: 'text',
	email: 'email',
	password: 'password',
}

function placeholderFor(input: AppInput): string {
	if (input.type === 'domain') return 'e.g. app.example.com'
	if (input.generate) return 'Leave blank to generate one'
	return ''
}
</script>

<template>
	<div class="grid gap-4 md:grid-cols-2">
		<div v-for="input in inputs" :key="input.name" class="space-y-1.5">
			<TextInput
				v-model="answers[input.name]"
				:label="input.label"
				:type="inputTypes[input.type]"
				:required="input.required"
				:placeholder="placeholderFor(input)"
				size="md"
				autocomplete="off"
			/>
			<p v-if="input.description" class="text-p-xs text-ink-gray-5">
				{{ input.description }}
			</p>
		</div>
	</div>
</template>
