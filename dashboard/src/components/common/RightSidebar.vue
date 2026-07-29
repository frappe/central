<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { Button } from 'frappe-ui'

// Shared detail slide-over. It is NOT a docked column — it overlays from the right
// and is only present while `open` (a row is selected). Pages own the body via the
// default slot and an optional #footer for actions.
//
// Motion (Emil Kowalski's drawer guidance): animate transform only — never width
// or layout — with an ease-out curve, quick (~280ms in, faster out), no overshoot.
// The scrim fades; the panel slides. Esc and scrim-click close it; the background
// scroll is locked while open.
const props = defineProps<{
	open: boolean
	title?: string
	subtitle?: string
}>()

const emit = defineEmits<{ close: [] }>()

function onKeydown(event: KeyboardEvent): void {
	if (event.key === 'Escape') emit('close')
}

function lockScroll(locked: boolean): void {
	document.body.style.overflow = locked ? 'hidden' : ''
}

watch(
	() => props.open,
	(open) => {
		lockScroll(open)
		if (open) document.addEventListener('keydown', onKeydown)
		else document.removeEventListener('keydown', onKeydown)
	},
)

onBeforeUnmount(() => {
	document.removeEventListener('keydown', onKeydown)
	lockScroll(false)
})
</script>

<template>
	<Teleport to="body">
		<Transition name="scrim">
			<div
				v-if="open"
				class="fixed inset-0 z-40 bg-black-overlay-200 dark:bg-black-overlay-700"
				@click="emit('close')"
			/>
		</Transition>

		<Transition name="panel">
			<aside
				v-if="open"
				class="fixed inset-y-0 right-0 z-50 flex w-[min(28rem,100vw)] flex-col bg-surface-elevation-1 shadow-2xl"
				role="dialog"
				aria-modal="true"
			>
				<header
					class="flex items-start justify-between gap-3 border-b border-outline-gray-2 px-5 py-4"
				>
					<div class="min-w-0">
						<h2 class="truncate text-lg font-semibold text-ink-gray-9">
							{{ title }}
						</h2>
						<p
							v-if="subtitle"
							class="mt-0.5 truncate text-p-sm text-ink-gray-5"
						>
							{{ subtitle }}
						</p>
					</div>
					<Button
						variant="ghost"
						icon="x"
						aria-label="Close"
						@click="emit('close')"
					/>
				</header>

				<div class="min-h-0 flex-1 overflow-y-auto px-5 py-5">
					<slot />
				</div>

				<footer
					v-if="$slots.footer"
					class="border-t border-outline-gray-2 px-5 py-4"
				>
					<slot name="footer" />
				</footer>
			</aside>
		</Transition>
	</Teleport>
</template>

<style scoped>
.panel-enter-active {
	transition: transform 0.28s cubic-bezier(0.32, 0.72, 0, 1);
}
.panel-leave-active {
	transition: transform 0.2s cubic-bezier(0.32, 0.72, 0, 1);
}
.panel-enter-from,
.panel-leave-to {
	transform: translateX(100%);
}

.scrim-enter-active,
.scrim-leave-active {
	transition: opacity 0.28s ease;
}
.scrim-enter-from,
.scrim-leave-to {
	opacity: 0;
}
</style>
