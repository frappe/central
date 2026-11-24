<script setup lang="ts">
import { Badge } from 'frappe-ui'
import type { ServerVisual } from '@/lib/serverMap'

interface ServerStatusBadgeProps {
	visual: ServerVisual
	size?: 'sm' | 'md'
}

withDefaults(defineProps<ServerStatusBadgeProps>(), { size: 'md' })
</script>

<template>
	<Badge :label="visual.label" :theme="visual.badgeTheme" :size="size">
		<template v-if="visual.icon" #prefix>
			<span :class="[visual.icon, '-m-px size-3']" aria-hidden="true" />
		</template>
	</Badge>
</template>
