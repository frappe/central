<script setup lang="ts">
import type { ServerMotion } from '@/lib/serverMap'

/**
 * The motion around a server avatar. A rotating arc is work under way, a pulsing
 * halo needs a person, and one green ring confirms that an action finished.
 * The parent sets the inset, so the ring fits any avatar size.
 */
interface StatusRingProps {
	motion: ServerMotion
	/** CSS colour of the arc or halo; the status dot's colour. */
	color: string
	isSettled?: boolean
	shape?: 'circle' | 'square'
}

withDefaults(defineProps<StatusRingProps>(), { shape: 'circle' })
</script>

<template>
	<span
		class="pointer-events-none absolute"
		:class="shape === 'square' ? 'rounded-5' : 'rounded-full'"
		aria-hidden="true"
	>
		<span
			v-if="motion === 'alert'"
			class="status-ring-alert absolute inset-0 rounded-[inherit]"
			:style="{ background: color }"
		/>
		<span
			v-else-if="motion === 'progress'"
			class="status-ring-progress absolute inset-0 rounded-[inherit]"
			:style="{ '--status-ring-color': color }"
		/>
		<span
			v-if="isSettled"
			class="status-ring-settled absolute inset-0 rounded-[inherit]"
		/>
	</span>
</template>

<style scoped>
.status-ring-alert {
	animation: status-ring-alert 1.8s ease-in-out infinite;
}
@keyframes status-ring-alert {
	0%,
	100% {
		opacity: 0.28;
	}
	50% {
		opacity: 0.08;
	}
}

@property --status-ring-angle {
	syntax: '<angle>';
	inherits: false;
	initial-value: 0deg;
}

.status-ring-progress {
	padding: 2px;
	background: conic-gradient(
		from var(--status-ring-angle),
		var(--status-ring-color) 0deg 90deg,
		color-mix(in srgb, var(--status-ring-color) 20%, transparent) 90deg 360deg
	);
	mask:
		linear-gradient(#000 0 0) content-box exclude,
		linear-gradient(#000 0 0);
	-webkit-mask:
		linear-gradient(#000 0 0) content-box xor,
		linear-gradient(#000 0 0);
	animation: status-ring-spin 1.1s linear infinite;
}
@keyframes status-ring-spin {
	to {
		--status-ring-angle: 360deg;
	}
}

.status-ring-settled {
	border: 2px solid var(--ink-green-6);
	animation: status-ring-settled 600ms cubic-bezier(0.23, 1, 0.32, 1) forwards;
}
@keyframes status-ring-settled {
	from {
		opacity: 1;
		transform: scale(0.9);
	}
	to {
		opacity: 0;
		transform: scale(1.4);
	}
}

@keyframes status-ring-settled-fade {
	to {
		opacity: 0;
	}
}

@media (prefers-reduced-motion: reduce) {
	.status-ring-alert {
		animation: none;
		opacity: 0.2;
	}
	.status-ring-progress {
		animation: none;
		opacity: 0.6;
	}
	.status-ring-settled {
		animation-name: status-ring-settled-fade;
	}
}
</style>
