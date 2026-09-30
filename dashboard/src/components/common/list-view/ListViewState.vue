<script setup lang="ts">
import { Alert, Button } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'

const props = defineProps<{
	kind: 'empty' | 'filtered' | 'error'
	title: string
	description?: string
}>()

defineEmits<{
	retry: []
	clear: []
}>()

const icons = {
	empty: 'lucide-inbox',
	filtered: 'lucide-search-x',
	error: 'lucide-circle-alert',
} as const
</script>

<template>
	<div
		v-if="kind === 'error'"
		class="flex min-h-64 items-center justify-center px-6"
	>
		<Alert
			class="w-full max-w-xl"
			theme="red"
			:title="title"
			:description="description"
			:primary-action="{ label: 'Try again', onClick: () => $emit('retry') }"
		/>
	</div>
	<EmptyState
		v-else
		:icon="icons[props.kind]"
		:title="title"
		:description="description"
	>
		<template v-if="kind === 'filtered'" #action>
			<Button label="Clear" @click="$emit('clear')" />
		</template>
		<template v-else-if="$slots.action" #action>
			<slot name="action" />
		</template>
	</EmptyState>
</template>
