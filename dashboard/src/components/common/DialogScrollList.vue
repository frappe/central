<script setup lang="ts">
import { ScrollArea } from 'frappe-ui'
import { onBeforeUnmount, onMounted, ref } from 'vue'

interface Props {
	fill?: boolean
}

defineProps<Props>()

type FadeEdges = 'top' | 'bottom' | 'both' | undefined

const area = ref<{ viewportElement: HTMLElement | null }>()
const fadeEdges = ref<FadeEdges>()
let observer: ResizeObserver | undefined

function updateFadeEdges(): void {
	const viewport = area.value?.viewportElement
	if (!viewport) return
	const above = viewport.scrollTop > 1
	const below =
		viewport.scrollTop + viewport.clientHeight < viewport.scrollHeight - 1
	fadeEdges.value =
		above && below ? 'both' : above ? 'top' : below ? 'bottom' : undefined
}

onMounted(() => {
	const viewport = area.value?.viewportElement
	if (!viewport) return
	viewport.addEventListener('scroll', updateFadeEdges, { passive: true })
	observer = new ResizeObserver(updateFadeEdges)
	observer.observe(viewport)
	if (viewport.firstElementChild) observer.observe(viewport.firstElementChild)
	updateFadeEdges()
})

onBeforeUnmount(() => {
	area.value?.viewportElement?.removeEventListener('scroll', updateFadeEdges)
	observer?.disconnect()
})
</script>

<template>
	<ScrollArea
		ref="area"
		class="dialog-scroll-list -my-1 -ml-1 -mr-4 sm:-mr-6"
		:class="{ 'flex min-h-0 flex-col': fill }"
		:data-fade="fadeEdges"
		:viewport-class="`${fill ? 'min-h-0' : 'max-h-80'} overscroll-contain py-1 pl-1 pr-4 sm:pr-6`"
	>
		<slot />
	</ScrollArea>
</template>

<style scoped>
.dialog-scroll-list {
	--fade: 1rem;
}
.dialog-scroll-list[data-fade="top"] :deep([data-slot="scroll-area-viewport"]) {
	mask-image: linear-gradient(to bottom, transparent, black var(--fade));
}
.dialog-scroll-list[data-fade="bottom"]
	:deep([data-slot="scroll-area-viewport"]) {
	mask-image: linear-gradient(
		to bottom,
		black calc(100% - var(--fade)),
		transparent
	);
}
.dialog-scroll-list[data-fade="both"]
	:deep([data-slot="scroll-area-viewport"]) {
	mask-image: linear-gradient(
		to bottom,
		transparent,
		black var(--fade),
		black calc(100% - var(--fade)),
		transparent
	);
}
</style>
