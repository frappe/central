<script lang="ts">
import type { InjectionKey } from 'vue'

export const SIDE_PANEL_CLOSE: InjectionKey<() => void> =
	Symbol('side-panel-close')
</script>

<script setup lang="ts">
import { Button } from 'frappe-ui'
import { inject } from 'vue'

// The inside of a SidePanel: header, scrollable body, pinned footer. Render it
// directly inside a `bare` SidePanel when several bodies share one panel, so
// each body keeps its own header while the panel itself stays put.
defineProps<{ title?: string; subtitle?: string }>()
const close = inject(SIDE_PANEL_CLOSE, () => {})
</script>

<template>
	<div
		class="flex items-start justify-between gap-3 border-b border-outline-gray-2 p-4"
	>
		<div class="min-w-0">
			<slot name="title">
				<div class="truncate text-base-semibold text-ink-gray-9">
					{{ title }}
				</div>
			</slot>
			<slot name="subtitle">
				<div v-if="subtitle" class="truncate text-p-sm text-ink-gray-5">
					{{ subtitle }}
				</div>
			</slot>
		</div>
		<div class="flex shrink-0 items-center gap-0.5">
			<slot name="actions" />
			<!-- `label` (not aria-label) is what frappe-ui's Button turns into
			     the accessible name; with `icon` set it renders no text. -->
			<Button variant="ghost" icon="lucide-x" label="Close" @click="close" />
		</div>
	</div>

	<div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
		<slot />
	</div>

	<div v-if="$slots.footer" class="border-t border-outline-gray-2 p-4">
		<slot name="footer" />
	</div>
</template>
