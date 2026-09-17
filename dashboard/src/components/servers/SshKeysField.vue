<script setup lang="ts">
import { Button, ErrorMessage, FormControl } from 'frappe-ui'
import { computed, ref } from 'vue'

// SSH keys matter for one image family only: Ubuntu has no web admin, so a machine
// created without a key is unreachable. Pilot users never need this, so the field stays
// behind a disclosure for them instead of asking everyone for a key they won't use.
const props = defineProps<{
	modelValue: string
	required: boolean
	problem: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const opened = ref(false)
const expanded = computed(
	() => props.required || opened.value || !!props.modelValue.trim(),
)
</script>

<template>
	<div>
		<Button
			v-if="!expanded"
			variant="ghost"
			size="sm"
			icon-left="lucide-key-round"
			label="Add SSH keys"
			@click="opened = true"
		/>
		<template v-else>
			<FormControl
				type="textarea"
				:label="required ? 'SSH public keys' : 'SSH public keys (optional)'"
				:model-value="modelValue"
				placeholder="One OpenSSH public key per line"
				spellcheck="false"
				autocapitalize="off"
				autocomplete="off"
				:aria-invalid="!!problem"
				@update:model-value="emit('update:modelValue', String($event))"
			/>
			<ErrorMessage v-if="problem" class="mt-1.5" :message="problem" />
			<p v-else class="mt-1.5 text-p-sm text-ink-gray-5">
				{{ required
						? 'Ubuntu has no web admin. This key is how you sign in.'
						: 'Pilot signs you in through the web admin. A key is only for shell access.' }}
			</p>
		</template>
	</div>
</template>
