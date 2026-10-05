<script setup lang="ts">
import { Alert, TextInput } from 'frappe-ui'
import { computed } from 'vue'
import { useCreateTeam } from '@/composables/useCreateTeam'

defineEmits<{ submit: [] }>()

const { teamName, name, duplicate, canSubmit, saving, error, submit } =
	useCreateTeam()

defineExpose({
	canSubmit,
	submitLabel: 'Create team',
	saving,
	submit,
})

const hint = computed(() =>
	duplicate.value
		? `You already have a team called “${name.value}”`
		: 'You can add a logo later in team settings.',
)
</script>

<template>
	<div class="space-y-4">
		<Alert v-if="error" theme="red" :title="error" />
		<div>
			<TextInput
				v-model="teamName"
				label="Team name"
				size="md"
				placeholder="e.g. Acme"
				autocomplete="off"
				v-focus
				@keyup.enter="$emit('submit')"
			/>
			<p
				class="mt-1.5 text-p-sm"
				:class="duplicate ? 'text-ink-red-5' : 'text-ink-gray-5'"
			>
				{{ hint }}
			</p>
		</div>
	</div>
</template>
