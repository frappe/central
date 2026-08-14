<script setup lang="ts">
import { computed } from 'vue'
import {
	capabilityLabel,
	groupCapabilitiesByCategory,
} from '@/lib/capabilities'
import type { CapabilityInfo } from '@/types/api'

// The granted capabilities of a role, grouped by area. `palette` is the full
// capability list, which resolves each name in `caps` to its description.
const props = withDefaults(
	defineProps<{
		caps: string[]
		palette: CapabilityInfo[]
	}>(),
	{
		caps: () => [],
		palette: () => [],
	},
)

const groups = computed(() => {
	const granted = new Set(props.caps)
	return groupCapabilitiesByCategory(
		props.palette.filter((cap) => granted.has(cap.name)),
	)
})
</script>

<template>
	<div v-if="caps.length" class="space-y-7">
		<section v-for="group in groups" :key="group.label">
			<h4
				class="mb-3 text-xs font-medium uppercase tracking-wide text-ink-gray-4"
			>
				{{ group.label }}
			</h4>
			<!-- Every row here is granted, so a per-row check said nothing — the
			     list itself is the grant. The slug stays a backend detail. -->
			<ul class="space-y-4">
				<li v-for="cap in group.caps" :key="cap.name" class="min-w-0">
					<p class="text-p-sm text-ink-gray-8">{{ capabilityLabel(cap) }}</p>
				</li>
			</ul>
		</section>
	</div>
	<p v-else class="text-p-sm text-ink-gray-5">
		This role grants no capabilities.
	</p>
</template>
