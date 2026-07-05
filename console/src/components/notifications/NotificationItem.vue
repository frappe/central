<script setup lang="ts">
import { computed } from 'vue'
import type { NotificationSeverity, TeamNotification } from '@/types/billing'

// One feed row, shared by the bell dropdown (compact) and the /notifications page.
const props = defineProps<{ notification: TeamNotification; compact?: boolean }>()
const emit = defineEmits<{ act: []; read: [] }>()

const SEVERITY: Record<NotificationSeverity, { icon: string; color: string }> = {
  Error: { icon: 'lucide-alert-circle', color: 'text-ink-red-3' },
  Warning: { icon: 'lucide-alert-triangle', color: 'text-ink-amber-3' },
  Success: { icon: 'lucide-check-circle-2', color: 'text-ink-green-3' },
  Info: { icon: 'lucide-info', color: 'text-ink-blue-3' },
}

const look = computed(() => SEVERITY[props.notification.severity] ?? SEVERITY.Info)

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
  <div
    class="flex gap-3 px-3 py-3"
    :class="[notification.is_read ? 'bg-surface-white' : 'bg-surface-gray-1', compact ? '' : 'sm:px-4']"
  >
    <span :class="[look.icon, look.color, 'mt-0.5 size-[18px] shrink-0']" aria-hidden="true" />

    <div class="min-w-0 flex-1">
      <div class="flex items-start justify-between gap-2">
        <p class="text-p-sm font-medium text-ink-gray-9" :class="compact ? 'truncate' : ''">
          {{ notification.title }}
        </p>
        <span class="shrink-0 whitespace-nowrap text-[11px] text-ink-gray-4">{{ when }}</span>
      </div>
      <p
        v-if="notification.message"
        class="mt-0.5 text-p-sm text-ink-gray-6"
        :class="compact ? 'line-clamp-2' : ''"
      >
        {{ notification.message }}
      </p>

      <div class="mt-1.5 flex items-center gap-3">
        <span
          class="rounded-full bg-surface-gray-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-gray-5"
        >
          {{ notification.category }}
        </span>
        <button
          v-if="notification.action_label"
          class="text-p-sm font-medium text-ink-gray-8 hover:text-ink-gray-9"
          @click="emit('act')"
        >
          {{ notification.action_label }} &rsaquo;
        </button>
        <button
          v-if="!notification.is_read"
          class="text-p-sm text-ink-gray-5 hover:text-ink-gray-8"
          @click="emit('read')"
        >
          Mark read
        </button>
      </div>
    </div>

    <span
      v-if="!notification.is_read"
      class="mt-1.5 size-2 shrink-0 rounded-full bg-surface-blue-5"
      aria-hidden="true"
    />
  </div>
</template>
