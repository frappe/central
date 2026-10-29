<script setup lang="ts">
import { Tooltip } from 'frappe-ui'

// Shared chrome for the consolidated Billing Overview cards (#69). Mirrors the
// frappe-cloud-v2 billing prototype: a rounded-6 hairline card with an inline
// semibold title (no header divider), an optional info tooltip beside the title,
// an optional header action slot, and a padded body.
defineProps<{ title: string; description?: string; titleInfo?: string }>()
</script>

<template>
	<section
		class="flex flex-col rounded-6 border border-outline-gray-1 bg-surface-base"
	>
		<header class="flex min-h-14 items-center justify-between gap-3 px-5 py-3">
			<div class="min-w-0">
				<div class="flex items-center gap-1.5">
					<h2 class="truncate text-base-semibold text-ink-gray-8">
						{{ title }}
					</h2>
					<Tooltip v-if="titleInfo" :text="titleInfo">
						<span
							class="lucide-info size-3.5 shrink-0 text-ink-gray-4"
							aria-hidden="true"
						/>
					</Tooltip>
				</div>
				<p v-if="description" class="mt-0.5 text-p-sm text-ink-gray-6">
					{{ description }}
				</p>
			</div>
			<div class="flex shrink-0 items-center">
				<slot name="action" />
			</div>
		</header>
		<!-- Only render the body when there is body content — a description-only
         card (e.g. Stop billing) would otherwise carry the body's empty
         padding as a phantom gap. -->
		<div v-if="$slots.default" class="flex flex-1 flex-col px-5 pb-5 pt-1">
			<slot />
		</div>
		<div v-else class="pb-4" />
		<slot name="footer" />
	</section>
</template>
