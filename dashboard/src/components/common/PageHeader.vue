<script setup lang="ts">
defineProps<{
	title: string
}>()
</script>

<template>
	<header
		class="flex h-12 items-center justify-between gap-3 border-b border-outline-gray-1 px-4 sm:px-6"
	>
		<h1 class="min-w-0 truncate text-lg font-medium text-ink-gray-9">
			{{ title }}
		</h1>
		<div class="flex shrink-0 items-center gap-2">
			<slot name="actions" />
		</div>
	</header>
</template>
