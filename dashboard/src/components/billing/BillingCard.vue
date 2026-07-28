<script setup lang="ts">
import { Tooltip } from "frappe-ui";

// Shared chrome for the consolidated Billing Overview cards (#69). Mirrors the
// frappe-cloud-v2 billing prototype: a rounded-xl hairline card with an inline
// semibold title (no header divider), an optional info tooltip beside the title,
// an optional header action slot, and a padded body.
defineProps<{ title: string; description?: string; titleInfo?: string }>();
</script>

<template>
	<section class="rounded-xl border border-outline-gray-2 bg-surface-elevation-1">
		<header class="flex items-center justify-between gap-3 px-5 pt-4">
			<div class="min-w-0">
				<div class="flex items-center gap-1.5">
					<h2 class="truncate text-base font-semibold text-ink-gray-8">
						{{ title }}
					</h2>
					<Tooltip v-if="titleInfo" :text="titleInfo">
						<span
							class="lucide-info size-3.5 shrink-0 text-ink-gray-4"
							aria-hidden="true"
						/>
					</Tooltip>
				</div>
				<p v-if="description" class="mt-0.5 text-p-sm text-ink-gray-5">
					{{ description }}
				</p>
			</div>
			<div class="shrink-0">
				<slot name="action" />
			</div>
		</header>
		<div class="px-5 pb-5 pt-4">
			<slot />
		</div>
	</section>
</template>
