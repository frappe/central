<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import NotificationItem from '@/components/notifications/NotificationItem.vue'
import NotificationPreferences from '@/components/notifications/NotificationPreferences.vue'
import { useNotifications } from '@/composables/useNotifications'
import type { TeamNotification } from '@/types/billing'

// Notifications — the full inbox (all history + inline actions) plus a Preferences
// tab that replaces the raw Desk form for delivery settings.
const { items, unread, loading, markAsRead, markAllAsRead } = useNotifications()
const router = useRouter()

const tab = ref<'inbox' | 'preferences'>('inbox')
type Filter = 'all' | 'unread' | 'Billing' | 'Server'
const filter = ref<Filter>('all')

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'unread', label: 'Unread' },
  { key: 'Billing', label: 'Billing' },
  { key: 'Server', label: 'Server' },
]

const visible = computed<TeamNotification[]>(() => {
  if (filter.value === 'all') return items.value
  if (filter.value === 'unread') return items.value.filter((n) => !n.is_read)
  return items.value.filter((n) => n.category === filter.value)
})

async function onAct(n: TeamNotification): Promise<void> {
  if (!n.is_read) await markAsRead(n.name)
  if (n.action_route) router.push(n.action_route)
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Notifications" subtitle="Team">
      <template #actions>
        <Button
          v-if="tab === 'inbox' && unread > 0"
          variant="subtle"
          label="Mark all read"
          @click="markAllAsRead"
        />
      </template>
    </PageHeader>

    <!-- Tabs -->
    <div class="flex gap-1 border-b border-outline-gray-1 px-4 sm:px-6">
      <button
        v-for="t in (['inbox', 'preferences'] as const)"
        :key="t"
        class="-mb-px border-b-2 px-3 py-2.5 text-sm capitalize"
        :class="tab === t
          ? 'border-outline-gray-5 font-medium text-ink-gray-9'
          : 'border-transparent text-ink-gray-5 hover:text-ink-gray-8'"
        @click="tab = t"
      >
        {{ t }}
      </button>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- INBOX -->
      <div v-if="tab === 'inbox'" class="mx-auto max-w-2xl px-4 py-5 sm:px-6">
        <div class="mb-4 flex flex-wrap gap-2">
          <button
            v-for="f in FILTERS"
            :key="f.key"
            class="rounded-full px-3 py-1 text-p-sm"
            :class="filter === f.key
              ? 'bg-surface-gray-4 text-ink-gray-9'
              : 'bg-surface-gray-2 text-ink-gray-6 hover:bg-surface-gray-3'"
            @click="filter = f.key"
          >
            {{ f.label }}
          </button>
        </div>

        <div v-if="loading && !items.length" class="p-4">
          <LoadingText :lines="6" />
        </div>
        <div
          v-else-if="visible.length"
          class="divide-y divide-outline-gray-1 overflow-hidden rounded-lg ring-1 ring-outline-gray-1"
        >
          <NotificationItem
            v-for="n in visible"
            :key="n.name"
            :notification="n"
            @act="onAct(n)"
            @read="markAsRead(n.name)"
          />
        </div>
        <div v-else class="rounded-lg border border-dashed border-outline-gray-2 px-4 py-16 text-center">
          <span class="lucide-bell-off mx-auto mb-2 block size-6 text-ink-gray-4" aria-hidden="true" />
          <p class="text-p-sm text-ink-gray-5">Nothing here yet.</p>
        </div>
      </div>

      <!-- PREFERENCES -->
      <div v-else class="px-4 py-5 sm:px-6">
        <NotificationPreferences />
      </div>
    </div>
  </div>
</template>
