<script setup lang="ts">
import { Button } from 'frappe-ui'
import { onBeforeUnmount, watch } from 'vue'

// The docked detail panel every page shares — a 24rem column that slides in
// beside the content (never over it), the billing invoice panel's anatomy made
// common. Pages own the body via the default slot; #title / #subtitle replace
// the text props for rich headers; #actions renders between the title block and
// the built-in close button; #footer pins below the scrollable body.
//
// Hosting: render as the last child of a `flex h-full` row, after the page's
// own `min-w-0 flex-1 overflow-y-auto` content column.
defineProps<{ title?: string; subtitle?: string }>()
const open = defineModel<boolean>('open', { default: false })

// The panel is docked, not modal, so it never holds focus — Esc has to be
// caught on the document. A stacked dialog owns Esc first: closing both at once
// would take the panel away for what read as one dismissal.
function onEscape(event: KeyboardEvent): void {
	if (event.key !== 'Escape') return
	if (document.querySelector('[role="dialog"]')) return
	open.value = false
}

watch(
	open,
	(isOpen) => {
		if (isOpen) document.addEventListener('keydown', onEscape)
		else document.removeEventListener('keydown', onEscape)
	},
	{ immediate: true },
)
onBeforeUnmount(() => document.removeEventListener('keydown', onEscape))
</script>

<template>
	<Transition name="slide" appear>
		<aside
			v-if="open"
			class="flex w-[24rem] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-base"
		>
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
					<Button
						variant="ghost"
						icon="lucide-x"
						label="Close"
						@click="open = false"
					/>
				</div>
			</div>

			<div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
				<slot />
			</div>

			<div v-if="$slots.footer" class="border-t border-outline-gray-2 p-4">
				<slot name="footer" />
			</div>
		</aside>
	</Transition>
</template>

<style scoped>
/* The margin animates alongside the slide: without it the panel's 24rem of
   layout width appears/disappears in a single frame. Margin animation costs
   layout per frame — the accepted tradeoff for a docked (not overlaid) panel. */

/* iOS drawer curve — decelerates hard at the end, so the panel settles rather
   than stops. */
.slide-enter-active {
	transition:
		transform 300ms cubic-bezier(0.32, 0.72, 0, 1),
		margin-inline-end 300ms cubic-bezier(0.32, 0.72, 0, 1);
}

/* Even in-out on the way out. The entrance curve reused here covers 80% of the
   travel in its first third then crawls, which reads as sticking; its exact
   mirror does the reverse and hangs for ~100ms after the click. */
.slide-leave-active {
	transition:
		transform 250ms cubic-bezier(0.65, 0, 0.35, 1),
		margin-inline-end 250ms cubic-bezier(0.65, 0, 0.35, 1);
}
.slide-enter-from,
.slide-leave-to {
	/* -24rem mirrors w-[24rem]: net layout width 0 while hidden. */
	transform: translateX(100%);
	margin-inline-end: -24rem;
}
</style>
