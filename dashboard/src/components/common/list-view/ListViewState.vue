<script setup lang="ts">
import { Button } from 'frappe-ui'
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
	<EmptyState
		:icon="icons[props.kind]"
		:title="title"
		:description="description"
	>
		<template v-if="kind === 'error'" #action>
			<Button
				label="Try again"
				icon-left="lucide-refresh-cw"
				@click="$emit('retry')"
			/>
		</template>
		<template v-else-if="kind === 'filtered'" #action>
			<Button label="Clear" @click="$emit('clear')" />
		</template>
		<template v-else-if="$slots.action" #action>
			<slot name="action" />
		</template>
	</EmptyState>
</template>
