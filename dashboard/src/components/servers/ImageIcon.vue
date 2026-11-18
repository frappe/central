<script setup lang="ts">
interface ImageIconProps {
	/** The Image Offering key, such as `pilot` or `ubuntu`. */
	offering?: string | null
}

defineProps<ImageIconProps>()

// Apps and unknown images have a lucide match; Frappe and Ubuntu are drawn on lucide's grid.
const LUCIDE_ICONS: Record<string, string> = {
	apps: 'lucide-package',
}
</script>

<template>
	<svg
		v-if="offering === 'pilot' || offering === 'ubuntu'"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		aria-hidden="true"
	>
		<template v-if="offering === 'pilot'">
			<rect x="3" y="3" width="18" height="18" rx="5" />
			<path d="M9 8.5h6" />
			<path d="M9.5 16.5v-4.5h5" />
		</template>
		<template v-else>
			<g fill="currentColor" stroke="none">
				<circle cx="3.75" cy="12" r="2.25" />
				<circle cx="16.12" cy="4.86" r="2.25" />
				<circle cx="16.12" cy="19.14" r="2.25" />
			</g>
			<path d="M7.23 8.78A5.75 5.75 0 0 1 11.6 6.26" />
			<path d="M17.17 9.48a5.75 5.75 0 0 1 0 5.04" />
			<path d="M11.6 17.74a5.75 5.75 0 0 1-4.37-2.52" />
		</template>
	</svg>
	<span
		v-else
		:class="LUCIDE_ICONS[offering ?? ''] ?? 'lucide-server'"
		aria-hidden="true"
	/>
</template>
