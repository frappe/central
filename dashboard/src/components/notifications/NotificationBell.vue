<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Popover } from 'frappe-ui'
import { useNotifications } from '@/composables/useNotifications'
import NotificationItem from '@/components/notifications/NotificationItem.vue'
import type { TeamNotification } from '@/types/billing'

// Topbar bell: an unread badge + a dropdown of the most recent items with inline
// actions. The full history + preferences live on the /notifications page.
const { items, unread, markAsRead, markAllAsRead } = useNotifications()
const router = useRouter()
const open = ref(false)

const recent = computed<TeamNotification[]>(() => items.value.slice(0, 6))
const badge = computed(() => (unread.value > 9 ? '9+' : String(unread.value)))

async function onAct(n: TeamNotification): Promise<void> {
	if (!n.is_read) await markAsRead(n.name)
	open.value = false
	if (n.action_route) router.push(n.action_route)
}

function seeAll(): void {
	open.value = false
	router.push('/notifications')
}
</script>

<template>
	<Popover v-model:open="open" placement="bottom-end">
		<template #trigger>
			<button
				class="relative flex size-8 items-center justify-center rounded-md text-ink-gray-7 hover:bg-surface-gray-2"
				aria-label="Notifications"
			>
				<span class="lucide-bell size-[18px]" aria-hidden="true" />
				<span
					v-if="unread > 0"
					class="absolute -right-0.5 -top-0.5 flex min-w-[16px] items-center justify-center rounded-full bg-surface-red-5 px-1 text-[10px] font-semibold leading-4 text-ink-white"
				>
					{{ badge }}
				</span>
			</button>
		</template>
		<template #body>
			<div
				class="mt-1 w-[22rem] overflow-hidden rounded-lg bg-surface-white shadow-2xl ring-1 ring-outline-gray-1"
			>
				<header
					class="flex items-center justify-between border-b border-outline-gray-1 px-3 py-2"
				>
					<span class="text-base font-semibold text-ink-gray-9"
						>Notifications</span
					>
					<button
						v-if="unread > 0"
						class="text-p-sm text-ink-gray-6 hover:text-ink-gray-9"
						@click="markAllAsRead"
					>
						Mark all read
					</button>
				</header>

				<div
					v-if="recent.length"
					class="max-h-[24rem] divide-y divide-outline-gray-1 overflow-y-auto"
				>
					<NotificationItem
						v-for="n in recent"
						:key="n.name"
						:notification="n"
						compact
						@act="onAct(n)"
						@read="markAsRead(n.name)"
					/>
				</div>
				<div v-else class="px-4 py-8 text-center text-p-sm text-ink-gray-5">
					You're all caught up.
				</div>

				<footer class="border-t border-outline-gray-1">
					<button
						class="w-full px-3 py-2 text-center text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2"
						@click="seeAll"
					>
						See all notifications
					</button>
				</footer>
			</div>
		</template>
	</Popover>
</template>
