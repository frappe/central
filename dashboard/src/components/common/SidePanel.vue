<script setup lang="ts">
import { Button } from 'frappe-ui'

interface Props {
	title?: string
	subtitle?: string
}

defineProps<Props>()

const open = defineModel<boolean>('open', { default: false })
</script>

<template>
	<Transition
		enter-active-class="transition-transform duration-300 ease-out md:transition-[margin,transform]"
		leave-active-class="transition-transform duration-200 ease-in md:transition-[margin,transform]"
		enter-from-class="translate-x-full md:-mr-[24rem]"
		leave-to-class="translate-x-full md:-mr-[24rem]"
	>
		<aside
			v-if="open"
			class="absolute inset-0 z-0 flex shrink-0 flex-col bg-surface-base md:static md:w-[24rem] md:border-l md:border-outline-gray-2"
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
					<Button
						variant="ghost"
						icon="lucide-x"
						label="Close"
						@click="open = false"
					/>
				</div>
			</div>

			<div
				class="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain"
			>
				<slot />
			</div>

			<div v-if="$slots.footer" class="border-t border-outline-gray-2 p-4">
				<slot name="footer" />
			</div>
		</aside>
	</Transition>
</template>
