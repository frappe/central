<script setup lang="ts">
interface Props {
	title: string
	description?: string
}

defineProps<Props>()
</script>

<template>
	<section class="overflow-hidden rounded-6 border border-outline-gray-2">
		<div class="space-y-4 p-5">
			<div>
				<h2 class="text-base-semibold text-ink-gray-8">{{ title }}</h2>
				<p v-if="description" class="mt-1 text-p-sm text-ink-gray-5">
					{{ description }}
				</p>
			</div>
			<slot />
		</div>
		<div
			v-if="$slots.footer"
			class="flex items-center justify-between gap-4 border-t border-outline-gray-2 px-5 py-3"
		>
			<slot name="footer" />
		</div>
	</section>
</template>
