<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'

interface RotatingTextProps {
	lines: string[]
	intervalMs?: number
}

const props = withDefaults(defineProps<RotatingTextProps>(), {
	intervalMs: 2600,
})

const index = ref(0)
let timer: ReturnType<typeof setInterval> | undefined

watch(
	() => props.lines.join('\n'),
	() => {
		clearInterval(timer)
		index.value = 0
		if (props.lines.length < 2) return
		timer = setInterval(() => {
			index.value = (index.value + 1) % props.lines.length
		}, props.intervalMs)
	},
	{ immediate: true },
)
onUnmounted(() => clearInterval(timer))
</script>

<template>
	<p class="relative h-6 overflow-hidden" aria-live="polite">
		<Transition name="line">
			<span v-if="lines.length" :key="lines[index]" class="block truncate">
				{{ lines[index] }}
			</span>
		</Transition>
	</p>
</template>

<style scoped>
/* The old line leaves fast and the new one settles slowly, so they read as one roll. */
.line-enter-active,
.line-leave-active {
	transition-property: transform, opacity, filter;
	transition-timing-function: cubic-bezier(0.23, 1, 0.32, 1);
}
.line-enter-active {
	transition-duration: 420ms;
	transition-delay: 60ms;
}
.line-leave-active {
	position: absolute;
	inset-inline: 0;
	transition-duration: 260ms;
}
.line-enter-from {
	opacity: 0;
	transform: translateY(55%);
	filter: blur(3px);
}
.line-leave-to {
	opacity: 0;
	transform: translateY(-55%);
	filter: blur(3px);
}

@media (prefers-reduced-motion: reduce) {
	.line-enter-from,
	.line-leave-to {
		transform: none;
		filter: none;
	}
}
</style>
