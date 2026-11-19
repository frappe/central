<script setup lang="ts">
import FrappeIcon from '@/components/icons/FrappeIcon.vue'
import UbuntuIcon from '@/components/icons/UbuntuIcon.vue'

interface ImageIconProps {
	/** The Image Offering key, such as `pilot` or `ubuntu`. */
	offering?: string | null
}

defineProps<ImageIconProps>()

const LUCIDE_ICONS: Record<string, string> = {
	apps: 'lucide-package',
}
</script>

<template>
	<FrappeIcon v-if="offering === 'pilot'" />

	<UbuntuIcon v-else-if="offering === 'ubuntu'" />

	<span
		v-else
		:class="LUCIDE_ICONS[offering ?? ''] ?? 'lucide-server'"
		aria-hidden="true"
	/>
</template>
