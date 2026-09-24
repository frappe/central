<script setup lang="ts">
import { onBeforeUnmount, provide, watch } from 'vue'
import SidePanelContent, {
	SIDE_PANEL_CLOSE,
} from '@/components/common/SidePanelContent.vue'

// The docked detail panel every page shares — a 24rem column that slides in
// beside the content (never over it), the billing invoice panel's anatomy made
// common. Pages own the body via the default slot; #title / #subtitle replace
// the text props for rich headers; #actions renders between the title block and
// the built-in close button; #footer pins below the scrollable body.
//
// `bare` drops the built-in SidePanelContent so the default slot supplies it.
// A page with several trays uses that to keep one panel open while its body
// swaps; `closed` fires once the slide-out ends, when the body can go.
//
// Hosting: render as the last child of a `flex h-full` row, after the page's
// own `min-w-0 flex-1 overflow-y-auto` content column.
defineProps<{ title?: string; subtitle?: string; bare?: boolean }>()
const emit = defineEmits<{ closed: [] }>()
const open = defineModel<boolean>('open', { default: false })

function close(): void {
	open.value = false
}
provide(SIDE_PANEL_CLOSE, close)

// The panel is docked, not modal, so it never holds focus — Esc has to be
// caught on the document. A stacked dialog owns Esc first: closing both at once
// would take the panel away for what read as one dismissal.
function onEscape(event: KeyboardEvent): void {
	if (event.key !== 'Escape') return
	if (document.querySelector('[role="dialog"]')) return
	close()
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
	<Transition name="slide" appear @after-leave="emit('closed')">
		<aside
			v-if="open"
			class="flex w-[24rem] shrink-0 flex-col border-l border-outline-gray-2 bg-surface-base"
		>
			<slot v-if="bare" />
			<SidePanelContent v-else :title="title" :subtitle="subtitle">
				<template v-for="(_, name) in $slots" #[name]>
					<slot :name="name" />
				</template>
			</SidePanelContent>
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
