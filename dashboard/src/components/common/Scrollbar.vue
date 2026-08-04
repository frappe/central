<script setup lang="ts">
import {
	ScrollAreaRoot,
	ScrollAreaViewport,
	ScrollAreaThumb,
	ScrollAreaScrollbar,
} from 'reka-ui'

interface Props {
	as?: string
}

defineProps<Props>()
</script>

<template>
	<ScrollAreaRoot
		class="relative overflow-hidden"
		style="--scrollbar-size: 10px"
		:scroll-hide-delay="0"
	>
		<ScrollAreaViewport class="h-full w-full" :as>
			<slot />
		</ScrollAreaViewport>

		<ScrollAreaScrollbar
			class="z-20 flex touch-none select-none p-0.5 transition-colors duration-[160ms] ease-out data-[orientation=vertical]:w-2.5"
			orientation="vertical"
		>
			<ScrollAreaThumb
				class="relative flex-1 rounded-[10px] bg-surface-gray-3"
			/>
		</ScrollAreaScrollbar>

		<ScrollAreaScrollbar
			class="z-20 flex touch-none select-none p-0.5 transition-colors duration-[160ms] ease-out data-[orientation=horizontal]:h-2.5"
			orientation="horizontal"
		>
			<ScrollAreaThumb
				class="relative flex-1 rounded-[10px] bg-surface-gray-3 before:absolute before:left-1/2 before:top-1/2 before:h-full before:min-h-[44px] before:w-full before:min-w-[44px] before:-translate-x-1/2 before:-translate-y-1/2 before:content-['']"
			/>
		</ScrollAreaScrollbar>
	</ScrollAreaRoot>
</template>
