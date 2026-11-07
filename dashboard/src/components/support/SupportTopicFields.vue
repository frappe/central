<script setup lang="ts">
import { Alert, Button, Select, Skeleton } from 'frappe-ui'
import { computed } from 'vue'
import type {
	SupportCategoryKey,
	SupportCategoryOption,
} from '@/composables/useSupport'
import { getErrorMessage } from '@/lib/feedback'

interface Props {
	options: SupportCategoryOption[]
	loading: boolean
	finished: boolean
	error: unknown
}

const props = defineProps<Props>()
const emit = defineEmits<{ retryOptions: [] }>()
const category = defineModel<SupportCategoryKey | ''>('category', {
	required: true,
})
const issueType = defineModel<string>('issueType', { required: true })

const categoryOptions = computed(() =>
	props.options.map((option) => ({ value: option.key, label: option.label })),
)
const selectedCategory = computed(
	() => props.options.find((option) => option.key === category.value) ?? null,
)
const issueOptions = computed(() =>
	(selectedCategory.value?.issues ?? []).map((issue) => ({
		value: issue.label,
		label: issue.label,
	})),
)
</script>

<template>
	<div class="space-y-3">
		<div
			v-if="!options.length && !loading && finished"
			class="flex items-center justify-between gap-2"
		>
			<Alert
				theme="red"
				:title="getErrorMessage(error, 'The ticket categories could not load.')"
			/>
			<Button label="Retry" @click="emit('retryOptions')" />
		</div>

		<div
			v-if="loading && !options.length"
			class="grid grid-cols-2 gap-3"
			aria-busy="true"
		>
			<Skeleton class="h-9 rounded-4" />
			<Skeleton class="h-9 rounded-4" />
		</div>

		<div v-else class="grid grid-cols-2 gap-3">
			<Select
				v-model="category"
				label="Topic"
				:options="categoryOptions"
				placeholder="Choose a topic"
				required
			/>
			<Select
				v-model="issueType"
				label="Issue"
				:options="issueOptions"
				placeholder="Choose the issue"
				:disabled="!category"
				required
			/>
		</div>
	</div>
</template>
