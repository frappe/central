<script setup lang="ts">
import { Button } from 'frappe-ui'
import { nextTick, onBeforeUnmount, useTemplateRef, watch } from 'vue'
import { useIsMobile } from '@/composables/useIsMobile'

// The docked detail panel every page shares — a 24rem column that slides in
// beside the content (never over it), the billing invoice panel's anatomy made
// common. Pages own the body via the default slot; #title / #subtitle replace
// the text props for rich headers; #actions renders between the title block and
// the built-in close button; #footer pins below the scrollable body.
//
// Hosting: render as the last child of a `flex h-full` row, after the page's
// own `min-w-0 flex-1 overflow-y-auto` content column.
//
// Below `sm` there is no row to dock into — MobileShell owns the scroll, so
// pages make that row `sm:`-only and a docked panel would stack a 384px column
// under content on a 375px viewport. Same anatomy, presented as a sheet
// instead: full-screen over the page header and the bottom nav, with the close
// button (or Esc, on a keyboard) the only way out.
defineProps<{ title?: string; subtitle?: string }>()
const open = defineModel<boolean>('open', { default: false })

// Docked, the panel sits beside content that stays usable, so it is a
// complementary region. As a sheet it covers everything, so it has to say so —
// otherwise a screen reader walks straight into the page behind it.
const isMobile = useIsMobile()
const panel = useTemplateRef<HTMLElement>('panel')

// The panel is docked, not modal, so it never holds focus — Esc has to be
// caught on the document. A stacked dialog owns Esc first: closing both at once
// would take the panel away for what read as one dismissal. `:not()` on our own
// root because the sheet now carries role="dialog" itself and would otherwise
// match, killing Esc entirely.
function onEscape(event: KeyboardEvent): void {
	if (event.key !== 'Escape') return
	if (document.querySelector('[role="dialog"]:not([data-slot="side-panel"])'))
		return
	open.value = false
}

// A sheet is the only thing on screen, so it takes focus and gives it back —
// without this, Close leaves focus on a row that is no longer rendered and the
// next Tab restarts from the top of the document.
let restoreFocusTo: HTMLElement | null = null

watch(
	open,
	(isOpen) => {
		if (isOpen) {
			document.addEventListener('keydown', onEscape)
			if (isMobile.value) {
				restoreFocusTo = document.activeElement as HTMLElement | null
				void nextTick(() => panel.value?.focus())
			}
			return
		}
		document.removeEventListener('keydown', onEscape)
		restoreFocusTo?.focus?.()
		restoreFocusTo = null
	},
	{ immediate: true },
)
onBeforeUnmount(() => document.removeEventListener('keydown', onEscape))
</script>

<template>
	<!-- Once the sheet is fixed it stops sharing the page's scroll, so it has to
	     stop handing gestures back to it: `max-sm:overscroll-contain` for reaching
	     the end of the body, and touch-action for the rest.
	     `touch-pan-y`, not MobileShell's `touch-none`: the body is the tall thing
	     here (a year of payments, a full receipt), and whether an ancestor's
	     `touch-none` reaches down into a descendant scroller is exactly the kind of
	     thing that behaves one way in a desktop emulator and another on a phone.
	     Allowing the one gesture the sheet needs costs nothing — pinch-zoom and
	     horizontal pan stay blocked either way. -->
	<Transition name="slide" appear>
		<aside
			v-if="open"
			ref="panel"
			data-slot="side-panel"
			:role="isMobile ? 'dialog' : undefined"
			:aria-modal="isMobile ? 'true' : undefined"
			:aria-label="isMobile ? title : undefined"
			:tabindex="isMobile ? -1 : undefined"
			class="flex w-[24rem] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-base focus:outline-none max-sm:fixed max-sm:inset-0 max-sm:z-20 max-sm:w-full max-sm:touch-pan-y max-sm:border-l-0"
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

			<div
				class="flex min-h-0 flex-1 flex-col overflow-y-auto max-sm:overscroll-contain"
			>
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
   layout per frame — the accepted tradeoff for a docked (not overlaid) panel.
   Below `sm` there is no layout width to collapse: left/right/width are all set
   (inset-0 + w-full), which over-constrains the box, so `right` is dropped and
   the end margin never enters the equation. The translate alone carries the
   sheet in, which is the whole animation a full-screen sheet wants. */

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
