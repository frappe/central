<script setup lang="ts">
import { Tooltip } from 'frappe-ui'

interface Props {
	title: string
	help?: string
	description?: string
}

defineProps<Props>()
</script>

<template>
	<section class="space-y-4 py-6 first:pt-0">
		<header class="flex items-center justify-between gap-4">
			<div class="min-w-0 space-y-1">
				<div class="flex items-center gap-1.5">
					<h2 class="text-base-semibold text-ink-gray-8">{{ title }}</h2>

					<Tooltip v-if="help" :text="help">
						<button
							type="button"
							:aria-label="help"
							class="grid size-5 place-items-center rounded-4 text-ink-gray-5 hover:text-ink-gray-7"
						>
							<span class="lucide-info size-4" />
						</button>
					</Tooltip>
				</div>

				<p v-if="description" class="text-p-sm text-ink-gray-5">
					{{ description }}
				</p>
			</div>

			<slot name="actions" />
		</header>

		<slot />
	</section>
</template>
