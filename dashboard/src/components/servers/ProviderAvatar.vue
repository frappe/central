<script setup lang="ts">
import { computed } from 'vue'
import awsBadge from '@/assets/providers/Provider=AWS.svg'
import doBadge from '@/assets/providers/Provider=DO.svg'
import frappeBadge from '@/assets/providers/Provider=Frappe.svg'
import hetznerBadge from '@/assets/providers/Provider=Hetzner.svg'
import ociBadge from '@/assets/providers/Provider=OCI.svg'
import scalewayBadge from '@/assets/providers/Provider=Scaleway.svg'

const props = withDefaults(
	defineProps<{
		/** Atlas Instance `provider` value (e.g. "AWS"); null/unknown → monogram. */
		provider?: string | null
		size?: number
	}>(),
	{ provider: null, size: 32 },
)

const BADGES: Record<string, string> = {
	AWS: awsBadge,
	Hetzner: hetznerBadge,
	Frappe: frappeBadge,
	OCI: ociBadge,
	DigitalOcean: doBadge,
	Scaleway: scalewayBadge,
}

const src = computed(() =>
	props.provider ? (BADGES[props.provider] ?? null) : null,
)
const monogram = computed(
	() => props.provider?.trim().charAt(0).toUpperCase() || '?',
)
</script>

<template>
	<!-- Circular provider mark for map nodes and list rows, keyed by the Atlas
       Instance's `provider` field. Uses the dedicated Provider=*.svg badge
       assets (self-contained circle + baked shadow); an unknown or empty
       provider falls back to a monogram tile so the map never breaks on a
       provider Central hasn't heard of yet. -->
	<span
		class="block shrink-0 select-none"
		:style="{ width: `${size}px`, height: `${size}px` }"
	>
		<img
			v-if="src"
			:src="src"
			:alt="provider ?? ''"
			class="size-full"
			draggable="false"
		/>
		<span
			v-else
			class="grid size-full place-items-center overflow-hidden rounded-full bg-surface-gray-3 font-bold leading-none text-ink-gray-8"
			:style="{ fontSize: `${Math.round(size * 0.42)}px` }"
		>
			{{ monogram }}
		</span>
	</span>
</template>
