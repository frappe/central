<script setup lang="ts">
import { Button, Popover, Select, SidebarItem, TabButtons } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'
import Scrollbar from '@/components/common/Scrollbar.vue'
import { useNotifications } from '@/composables/useNotifications'
import type { NotificationSeverity, TeamNotification } from '@/types/billing'

const {
	items,
	unread,
	hasNextPage,
	loading,
	loadMore,
	markAsRead,
	markAllAsRead,
} = useNotifications()

const router = useRouter()
const open = ref(false)

const TABS = [
	{ label: 'All', value: 'all' },
	{ label: 'Unread', value: 'unread' },
]

const activeTab = ref('all')

const CATEGORIES = [
	{ label: 'All categories', value: '', icon: 'lucide-list' },
	{ label: 'Billing', value: 'Billing', icon: 'lucide-credit-card' },
	{ label: 'Server', value: 'Server', icon: 'lucide-server' },
	{ label: 'Team', value: 'Team', icon: 'lucide-users' },
]

const category = ref('')

const badge = computed(() =>
	unread.value > 0 ? (unread.value > 99 ? '99+' : String(unread.value)) : '',
)

const visible = computed<TeamNotification[]>(() =>
	items.value.filter(
		(n) =>
			(activeTab.value !== 'unread' || !n.is_read) &&
			(!category.value || n.category === category.value),
	),
)

const SEVERITY: Record<
	NotificationSeverity,
	{ icon: string; text: string; bg: string }
> = {
	Error: {
		icon: 'lucide-circle-alert',
		text: 'text-ink-red-8',
		bg: 'bg-surface-red-1',
	},
	Warning: {
		icon: 'lucide-triangle-alert',
		text: 'text-ink-amber-8',
		bg: 'bg-surface-amber-1',
	},
	Success: {
		icon: 'lucide-circle-check',
		text: 'text-ink-green-8',
		bg: 'bg-surface-green-1',
	},
	Info: {
		icon: 'lucide-info',
		text: 'text-ink-blue-8',
		bg: 'bg-surface-blue-1',
	},
}

const look = (severity: NotificationSeverity) =>
	SEVERITY[severity] ?? SEVERITY.Info

const timeAgo = (timestamp: string): string => {
	const then = new Date(timestamp.replace(' ', 'T')).getTime()

	if (Number.isNaN(then)) return ''

	const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000))
	if (seconds < 60) return 'just now'

	const minutes = Math.floor(seconds / 60)
	if (minutes < 60) return `${minutes}m ago`

	const hours = Math.floor(minutes / 60)
	if (hours < 24) return `${hours}h ago`

	const days = Math.floor(hours / 24)
	if (days < 30) return `${days}d ago`

	return new Date(then).toLocaleDateString()
}

const onRowClick = async (notification: TeamNotification): Promise<void> => {
	await markAsRead(notification.name)

	if (notification.action_route) {
		open.value = false
		router.push(notification.action_route)
	}
}
</script>

<template>
	<Popover
		v-model:open="open"
		bare
		side="right"
		align="start"
		:offset="9"
		:collision-padding="0"
	>
		<template #trigger>
			<SidebarItem label="Notifications" :suffix="badge" class="mb-3">
				<template #prefix>
					<span class="relative block size-4">
						<span class="lucide-bell block size-4" aria-hidden="true" />
						<span
							v-if="unread > 0"
							class="absolute right-[2px] top-0 block size-[5px] shrink-0 rounded-full bg-surface-blue-6"
							aria-hidden="true"
						/>
					</span>
				</template>
			</SidebarItem>
		</template>

		<!-- need shadow on right side only -->
		<aside
			class="flex h-screen w-screen flex-col border-outline-gray-1 bg-surface-base shadow-[6px_0_20px_-6px_rgb(0_0_0/0.10)] md:w-[430px] md:border-r"
		>
			<header
				class="flex items-center gap-1 border-b border-outline-gray-1 py-2 pl-4 pr-2"
			>
				<span class="mr-auto text-base font-medium">Notifications</span>

				<Button
					v-if="unread > 0"
					variant="ghost"
					icon="lucide-check-check"
					aria-label="Mark all as read"
					@click="markAllAsRead"
				/>
				<Button
					variant="ghost"
					icon="lucide-x"
					aria-label="Close notifications"
					@click="open = false"
				/>
			</header>

			<div class="flex flex-none items-center gap-2 px-4 py-3">
				<TabButtons v-model="activeTab" :options="TABS" />
				<Select v-model="category" class="ml-auto" :options="CATEGORIES" />
			</div>

			<Scrollbar v-if="visible.length">
				<button
					v-for="n, i in visible"
					:key="n.name"
					type="button"
					class="flex w-full cursor-pointer items-start gap-4 p-4 text-left hover:bg-surface-gray-1"
          :class="i == visible.length - 1 ? '' : 'border-b'"
					@click="onRowClick(n)"
				>
					<!-- severity square badge -->
					<span
						class="relative mt-0.5 grid size-8 shrink-0 place-items-center rounded"
						:class="look(n.severity).bg"
					>
						<span
							:class="[look(n.severity).icon, look(n.severity).text, 'size-4']"
							aria-hidden="true"
						/>
						<span
							v-if="!n.is_read"
							class="absolute -right-px -top-px block size-1.5 shrink-0 rounded-full bg-surface-blue-5"
							aria-hidden="true"
						/>
					</span>

					<!-- notif tile body -->
					<span class="min-w-0 flex-1">
						<span class="flex items-start gap-2">
							<span
								class="min-w-0 flex-1 text-base font-medium text-ink-gray-9"
							>
								{{ n.title }}
							</span>
							<span class="shrink-0 whitespace-nowrap text-xs text-ink-gray-5">
								{{ timeAgo(n.creation) }}
							</span>
						</span>

						<span
							v-if="n.message"
							class="mt-0.5 block text-p-sm text-ink-gray-6"
						>
							{{ n.message }}
						</span>
					</span>
				</button>
			</Scrollbar>

			<div v-else class="min-h-0 flex-1 px-4 pb-3">
				<EmptyState
					v-if="activeTab === 'unread'"
					icon="lucide-check-check"
					title="You're all caught up"
					description="Every notification for this team has been read."
				/>
				<EmptyState
					v-else
					icon="lucide-bell-off"
					title="Nothing here yet"
					description="Billing and server alerts for your team will show up here."
				/>
			</div>

			<footer
				v-if="hasNextPage"
				class="mt-auto flex justify-end border-outline-gray-1 p-2"
			>
				<Button label="Load More" :loading="loading" @click="loadMore" />
			</footer>
		</aside>
	</Popover>
</template>
