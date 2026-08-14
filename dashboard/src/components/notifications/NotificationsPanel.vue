<script setup lang="ts">
import {
	Button,
	dayjsLocal,
	MobileNavItem,
	Popover,
	Select,
	SidebarItem,
	TabButtons,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'
import Scrollbar from '@/components/common/Scrollbar.vue'
import { useIsMobile } from '@/composables/useIsMobile'
import { useNotifications } from '@/composables/useNotifications'
import type { NotificationSeverity, TeamNotification } from '@/types/billing'

const {
	items,
	category,
	unreadOnly,
	unread,
	hasNextPage,
	loading,
	loadMore,
	markAsRead,
	markAllAsRead,
} = useNotifications()

defineProps<{ mobile?: boolean }>()

const router = useRouter()
const isMobile = useIsMobile()
const open = ref(false)

const TABS = [
	{ label: 'All', value: 'all' },
	{ label: 'Unread', value: 'unread' },
]

const activeTab = computed({
	get: () => (unreadOnly.value ? 'unread' : 'all'),
	set: (value: string) => {
		unreadOnly.value = value === 'unread'
	},
})

const CATEGORIES = [
	{ label: 'All categories', value: '', icon: 'lucide-list' },
	{ label: 'Billing', value: 'Billing', icon: 'lucide-credit-card' },
	{ label: 'Server', value: 'Server', icon: 'lucide-server' },
	{ label: 'Team', value: 'Team', icon: 'lucide-users' },
]

const badge = computed(() =>
	unread.value > 0 ? (unread.value > 99 ? '99+' : String(unread.value)) : '',
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
		:side="isMobile ? 'top' : 'right'"
		align="start"
		:offset="isMobile ? 0 : 9"
		:collision-padding="0"
	>
		<template #trigger>
			<MobileNavItem v-if="mobile" label="Notifications">
				<span class="relative block size-6">
					<span
						class="lucide-bell block size-6 text-ink-gray-5"
						aria-hidden="true"
					/>
					<span
						v-if="unread > 0"
						class="absolute right-0 top-0 block size-1.5 shrink-0 rounded-full bg-surface-blue-6"
						aria-hidden="true"
					/>
				</span>
			</MobileNavItem>

			<SidebarItem v-else label="Notifications" :suffix="badge" class="mb-3">
				<template #prefix>
					<span class="relative block size-4">
						<span class="lucide-bell block size-4" aria-hidden="true" />
						<span
							v-if="unread > 0"
							class="absolute right-[1px] top-0 block size-[5px] shrink-0 rounded-full bg-surface-blue-6"
							aria-hidden="true"
						/>
					</span>
				</template>
			</SidebarItem>
		</template>

		<!-- need shadow on right side only -->
		<aside
			class="flex h-[calc(100dvh-3.5rem)] w-screen flex-col border-outline-gray-1 bg-surface-base shadow-[6px_0_20px_-6px_rgb(0_0_0/0.10)] md:h-screen md:w-[430px] md:border-r"
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

			<Scrollbar v-if="items.length" class="min-h-0 flex-1">
				<button
					v-for="n, i in items"
					:key="n.name"
					type="button"
					class="flex w-full cursor-pointer items-start gap-4 p-4 text-left hover:bg-surface-gray-1"
          :class="i == items.length - 1 ? '' : 'border-b'"
					@click="onRowClick(n)"
				>
					<!-- severity square badge -->
					<span
						class="relative mt-0.5 grid size-8 shrink-0 place-items-center rounded-4"
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
								{{ dayjsLocal(n.creation).fromNow() }}
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
