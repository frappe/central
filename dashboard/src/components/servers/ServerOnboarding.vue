<script setup lang="ts">
import { Button } from 'frappe-ui'

// First-run nudge on the servers map: one clear action (create a server), and a
// close button so it never gets in the way. Purely presentational — the parent
// decides when to show it and remembers the dismissal.
defineEmits<{ create: []; dismiss: [] }>()
</script>

<template>
	<div class="absolute bottom-4 left-4 z-20 w-72 max-w-[calc(100%-2rem)]">
		<div
			class="relative rounded-7 border border-outline-gray-2 bg-surface-elevation-1 p-4 shadow-lg"
		>
			<button
				class="absolute right-2 top-2 grid size-6 place-items-center rounded-5 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-7"
				aria-label="Dismiss"
				@click="$emit('dismiss')"
			>
				<span class="lucide-x size-4" />
			</button>

			<div
				class="flex size-8 items-center justify-center rounded-6 bg-surface-gray-2 text-ink-gray-7"
			>
				<span class="lucide-server size-4" />
			</div>
			<p class="mt-3 text-base font-medium text-ink-gray-9">
				Create your first server
			</p>
			<p class="mt-1 text-p-sm text-ink-gray-5">
				Your sites will run on it. Start here, or pick a
				<span class="font-medium text-ink-gray-7">+</span>
				spot on the map.
			</p>
			<Button
				class="mt-3"
				variant="solid"
				label="New server"
				icon-left="lucide-plus"
				@click="$emit('create')"
			/>
		</div>
	</div>
</template>
