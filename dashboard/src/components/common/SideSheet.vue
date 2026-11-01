<script setup lang="ts">
import { Button } from 'frappe-ui'
import {
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogOverlay,
	DialogPortal,
	DialogRoot,
	DialogTitle,
} from 'reka-ui'

interface Props {
	title: string
	description?: string
}

defineProps<Props>()

const open = defineModel<boolean>('open', { default: false })
</script>

<template>
	<DialogRoot v-model:open="open">
		<DialogPortal>
			<DialogOverlay
				class="side-sheet-overlay fixed inset-0 z-50 bg-black-overlay-200 dark:bg-black-overlay-700"
			/>
			<DialogContent
				class="side-sheet fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-outline-gray-1 bg-surface-base shadow-xl focus-visible:outline-none"
			>
				<header
					class="flex items-start justify-between gap-3 border-b border-outline-gray-1 px-5 py-4"
				>
					<div class="min-w-0">
						<DialogTitle class="text-lg-semibold text-ink-gray-9">
							{{ title }}
						</DialogTitle>
						<DialogDescription
							v-if="description"
							class="mt-1 text-p-sm text-ink-gray-6"
						>
							{{ description }}
						</DialogDescription>
					</div>
					<div class="flex shrink-0 items-center gap-1">
						<slot name="actions" />
						<DialogClose as-child>
							<Button variant="ghost" icon="lucide-x" label="Close" />
						</DialogClose>
					</div>
				</header>

				<div class="min-h-0 flex-1 overflow-y-auto overscroll-contain">
					<slot />
				</div>

				<footer
					v-if="$slots.footer"
					class="border-t border-outline-gray-1 px-5 py-4"
				>
					<slot name="footer" />
				</footer>
			</DialogContent>
		</DialogPortal>
	</DialogRoot>
</template>

<style scoped>
.side-sheet-overlay[data-state="open"] {
	animation: side-sheet-fade-in 160ms ease-out;
}
.side-sheet-overlay[data-state="closed"] {
	animation: side-sheet-fade-out 140ms ease-in;
}
.side-sheet[data-state="open"] {
	animation: side-sheet-slide-in 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.side-sheet[data-state="closed"] {
	animation: side-sheet-slide-out 160ms ease-in;
}

@keyframes side-sheet-fade-in {
	from {
		opacity: 0;
	}
}
@keyframes side-sheet-fade-out {
	to {
		opacity: 0;
	}
}
@keyframes side-sheet-slide-in {
	from {
		transform: translateX(1.5rem);
		opacity: 0;
	}
}
@keyframes side-sheet-slide-out {
	to {
		transform: translateX(1.5rem);
		opacity: 0;
	}
}

@media (prefers-reduced-motion: reduce) {
	.side-sheet,
	.side-sheet-overlay {
		animation: none !important;
	}
}
</style>
