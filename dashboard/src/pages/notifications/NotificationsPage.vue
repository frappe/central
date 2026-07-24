<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Dialog, LoadingText, TabButtons } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import NotificationItem from '@/components/notifications/NotificationItem.vue'
import NotificationPreferences from '@/components/notifications/NotificationPreferences.vue'
import { useNotifications } from '@/composables/useNotifications'
import type { TeamNotification } from '@/types/billing'

// Notifications — the full inbox (all history + inline actions). Delivery
// preferences live in a dialog behind the header's settings button.
const { items, unread, loading, markAsRead, markAllAsRead } = useNotifications()
const router = useRouter()

const preferencesOpen = ref(false)

type Filter = 'all' | 'unread' | 'Billing' | 'Server'
const filter = ref<Filter>('all')

const FILTERS: { label: string; value: Filter }[] = [
	{ label: 'All', value: 'all' },
	{ label: 'Unread', value: 'unread' },
	{ label: 'Billing', value: 'Billing' },
	{ label: 'Server', value: 'Server' },
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
		<Teleport to="#header-actions">
			<Button
				v-if="unread > 0"
				variant="subtle"
				label="Mark all read"
				@click="markAllAsRead"
			/>
			<Button
				variant="ghost"
				icon="lucide-settings-2"
				aria-label="Notification preferences"
				@click="preferencesOpen = true"
			/>
		</Teleport>

		<div class="min-h-0 flex-1 overflow-y-auto">
			<div class="mx-auto max-w-2xl px-4 py-5 sm:px-6">
				<TabButtons v-model="filter" :options="FILTERS" class="mb-4" />

				<div v-if="loading && !items.length" class="p-4">
					<LoadingText :lines="6" />
				</div>
				<div v-else-if="visible.length" class="divide-y divide-outline-gray-1">
					<NotificationItem
						v-for="n in visible"
						:key="n.name"
						:notification="n"
						@act="onAct(n)"
						@read="markAsRead(n.name)"
					/>
				</div>
				<EmptyState
					v-else
					icon="lucide-bell-off"
					title="Nothing here yet"
					description="Billing and server alerts for your team will show up here."
				/>
			</div>
		</div>

		<Dialog v-model:open="preferencesOpen" title="Notification preferences">
			<template #default>
				<NotificationPreferences />
			</template>
		</Dialog>
	</div>
</template>
