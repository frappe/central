<script setup lang="ts">
import { computed } from 'vue'
import type { NotificationSeverity, TeamNotification } from '@/types/billing'

// One feed row, shared by the bell dropdown (compact) and the /notifications page.
// Plain list row: no background, no border — unread is the blue dot by the time.
// Category is not shown here; it only drives the page's filter tabs.
const props = defineProps<{
	notification: TeamNotification
	compact?: boolean
}>()
const emit = defineEmits<{ act: []; read: [] }>()

// ink-8 across the board: the -3 steps are near-white background tints, so the
// icon all but disappeared on a light surface.
const SEVERITY: Record<NotificationSeverity, { icon: string; color: string }> =
	{
		Error: { icon: 'lucide-alert-circle', color: 'text-ink-red-7' },
		Warning: { icon: 'lucide-alert-triangle', color: 'text-ink-amber-7' },
		Success: { icon: 'lucide-check-circle-2', color: 'text-ink-green-7' },
		Info: { icon: 'lucide-info', color: 'text-ink-blue-7' },
	}

const look = computed(
	() => SEVERITY[props.notification.severity] ?? SEVERITY.Info,
)

const when = computed(() => timeAgo(props.notification.creation))

function timeAgo(ts: string): string {
	const then = new Date(ts.replace(' ', 'T')).getTime()
	if (Number.isNaN(then)) return ''
	const secs = Math.max(0, Math.floor((Date.now() - then) / 1000))
	if (secs < 60) return 'just now'
	const mins = Math.floor(secs / 60)
	if (mins < 60) return `${mins}m ago`
	const hrs = Math.floor(mins / 60)
	if (hrs < 24) return `${hrs}h ago`
	const days = Math.floor(hrs / 24)
	if (days < 30) return `${days}d ago`
	return new Date(then).toLocaleDateString()
}
</script>

<template>
	<div class="flex gap-3 py-3" :class="compact ? 'px-3' : ''">
		<span
			:class="[look.icon, look.color, 'mt-0.5 size-4 shrink-0']"
			aria-hidden="true"
		/>

		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-2">
				<p
					class="min-w-0 flex-1 text-base-medium text-ink-gray-9"
					:class="compact ? 'truncate' : ''"
				>
					{{ notification.title }}
				</p>
				<span class="shrink-0 whitespace-nowrap text-p-sm text-ink-gray-4"
					>{{ when }}</span
				>
				<span
					v-if="!notification.is_read"
					class="size-1.5 shrink-0 rounded-full bg-surface-blue-5"
					aria-hidden="true"
				/>
			</div>

			<p
				v-if="notification.message"
				class="mt-0.5 text-p-sm text-ink-gray-6"
				:class="compact ? 'line-clamp-2' : ''"
			>
				{{ notification.message }}
			</p>

			<div
				v-if="notification.action_label || !notification.is_read"
				class="mt-2 flex items-center gap-4"
			>
				<button
					v-if="notification.action_label"
					class="text-p-sm font-medium text-ink-gray-8 hover:text-ink-gray-9"
					@click="emit('act')"
				>
					{{ notification.action_label }}
					&rsaquo;
				</button>
				<button
					v-if="!notification.is_read"
					class="text-p-sm text-ink-gray-5 hover:text-ink-gray-8"
					@click="emit('read')"
				>
					Mark as read
				</button>
			</div>
		</div>
	</div>
</template>
