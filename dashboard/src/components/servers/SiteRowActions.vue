<script setup lang="ts">
import { computed } from 'vue'
import { Button, Dropdown } from 'frappe-ui'

// The actions menu for one site row in the unified assets list. A site is a
// 1:1-backed VM, so it reuses the server capabilities (site-level caps are
// deferred). Presentational — it emits the verb; the page owns the calls.
const props = defineProps<{
	site: { name: string; url: string | null }
	canOpen: boolean
	canTerminate: boolean
	busy?: boolean
}>()

const emit = defineEmits<{
	open: [url: string]
	terminate: [name: string]
}>()

const options = computed(() => {
	const items = []
	if (props.canOpen && props.site.url)
		items.push({ label: 'Open site', icon: 'lucide-external-link', onClick: () => emit('open', props.site.url!) })
	if (props.canTerminate)
		items.push({ label: 'Terminate', icon: 'lucide-trash-2', theme: 'red' as const, onClick: () => emit('terminate', props.site.name) })
	return items
})
</script>

<template>
	<Dropdown v-if="options.length" :options="options" placement="right">
		<Button variant="ghost" icon="lucide-more-horizontal" :loading="busy" aria-label="Site actions" />
	</Dropdown>
</template>
