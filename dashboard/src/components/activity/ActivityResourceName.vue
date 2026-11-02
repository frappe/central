<script setup lang="ts">
import { computed } from 'vue'
import type { ActivityResource } from '@/types/activity'

/** The resource an event names, linked when it has a page of its own. */
interface Props {
	resource: ActivityResource
	link: boolean
}

const props = defineProps<Props>()

// Only servers have a detail page today.
const route = computed(() =>
	props.link && props.resource.type === 'Virtual Machine'
		? { name: 'Server', params: { id: props.resource.name } }
		: null,
)
</script>

<template>
	<RouterLink
		v-if="route"
		:to="route"
		class="text-base-medium text-ink-gray-9 underline-offset-2 hover:underline focus-visible:rounded-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
		@click.stop
	>
		{{ resource.label }}
	</RouterLink>
	<span v-else class="text-base-medium text-ink-gray-9"
		>{{ resource.label }}</span
	>
</template>
