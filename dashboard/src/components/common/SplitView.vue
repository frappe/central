<script setup lang="ts">
// List-left / detail-right master–detail. The list grows; the detail is a fixed
// ~480px panel pinned right (border-l), NOT a modal — a modal is reserved for
// actions. On mobile the detail slides over the list full-screen.
//
// `open` (v-model) tracks whether a row is selected, so the parent can clear it.
// The panel owns its own dismiss control: "← Back" on mobile, a close (✕) on
// desktop — the list underneath stays put, so closing is always one click away.
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
	<div class="flex min-h-0 flex-1">
		<!-- List -->
		<div
			class="min-w-0 flex-1 overflow-y-auto"
			:class="open ? 'hidden sm:block' : 'block'"
		>
			<slot name="list" />
		</div>

		<!-- Detail -->
		<aside
			v-if="open"
			class="flex w-full shrink-0 flex-col overflow-y-auto border-outline-gray-1 sm:w-[480px] sm:border-l"
		>
			<div
				class="flex items-center justify-between gap-2 border-b border-outline-gray-1 px-4 py-2.5"
			>
				<button
					class="shrink-0 text-p-sm text-ink-gray-6 sm:hidden"
					aria-label="Back"
					@click="open = false"
				>
					← Back
				</button>
				<!-- Panel title — defaults to "Details", but the parent can replace it with
             document context (e.g. the selected invoice's number + period). -->
				<div class="min-w-0 flex-1">
					<slot name="header">
						<span
							class="text-p-sm font-medium uppercase tracking-wide text-ink-gray-5"
						>
							Details
						</span>
					</slot>
				</div>
				<div class="ml-auto flex shrink-0 items-center gap-1">
					<!-- Document-level actions (e.g. email / download), pinned to the top of
               the panel beside the close control rather than buried in the body. -->
					<slot name="actions" />
					<button
						class="grid size-6 place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
						aria-label="Close details"
						@click="open = false"
					>
						<span class="lucide-x size-4" aria-hidden="true" />
					</button>
				</div>
			</div>
			<slot name="detail" />
		</aside>
	</div>
</template>
