<script setup lang="ts">
import { Avatar } from 'frappe-ui'
import type { ActivityActor } from '@/types/activity'

/** A person's avatar, or the event's kind for work the system did. */
interface Props {
	actor: ActivityActor
	/** Icon class shown in place of a system avatar. */
	icon: string
	failed?: boolean
}

withDefaults(defineProps<Props>(), { failed: false })
</script>

<template>
	<Avatar
		v-if="actor.kind === 'user'"
		:label="actor.label"
		:image="actor.image ?? undefined"
		size="lg"
		class="shrink-0"
	/>
	<span
		v-else
		class="flex size-7 shrink-0 items-center justify-center rounded-full"
		:class="
			failed
				? 'bg-surface-red-1 text-ink-red-6'
				: 'bg-surface-gray-2 text-ink-gray-6'
		"
		aria-hidden="true"
	>
		<span :class="icon" class="size-3.5" />
	</span>
</template>
