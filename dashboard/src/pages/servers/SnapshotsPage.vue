<script setup lang="ts">
import { useRoute } from 'vue-router'
import SnapshotsPanel from '@/components/snapshots/SnapshotsPanel.vue'

const route = useRoute()
const initialSearch =
	typeof route.query.search === 'string' ? route.query.search : ''
</script>

<template>
	<div class="h-full overflow-y-auto">
		<SnapshotsPanel
			:initial-search="initialSearch"
			class="mx-auto w-full max-w-5xl px-6 py-8"
		/>
	</div>
</template>
