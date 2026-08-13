<script setup lang="ts">
import {
	Breadcrumbs,
	Button,
	LoadingText,
	PageHeader,
	PageHeaderMobile,
	TabButtons,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'
import NotificationItem from '@/components/notifications/NotificationItem.vue'
import { useNotifications } from '@/composables/useNotifications'
import { openSettings } from '@/composables/useSettings'
import type { TeamNotification } from '@/types/billing'

// Notifications — the full inbox (all history + inline actions). Delivery
// preferences are a tab in the shared settings dialog, opened from the header's
// settings button.
const { items, unread, loading, markAsRead, markAllAsRead } = useNotifications()
const router = useRouter()

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
	<PageHeaderMobile class="sm:hidden" title="Notifications">
		<template #suffix>
			<Button
				variant="ghost"
				size="md"
				icon="lucide-settings-2"
				label="Notification preferences"
				@click="openSettings('notifications')"
			/>
		</template>
	</PageHeaderMobile>

	<PageHeader class="hidden sm:flex">
		<Breadcrumbs
			:items="[{ label: 'Notifications', route: { name: 'Notifications' } }]"
		/>
		<div class="flex items-center gap-2">
			<Button
				v-if="unread > 0"
				variant="subtle"
				label="Mark all read"
				@click="markAllAsRead"
			/>
			<Button
				variant="ghost"
				icon="lucide-settings-2"
				label="Notification preferences"
				@click="openSettings('notifications')"
			/>
		</div>
	</PageHeader>

	<!-- Desktop-only scroll scaffolding: DesktopShell doesn't scroll, so the page
	     owns its overflow there. On mobile MobileShell is the scroller and this
	     falls through to it. -->
	<div class="sm:flex sm:h-full sm:flex-col">
		<div class="sm:min-h-0 sm:flex-1 sm:overflow-y-auto">
			<div class="mx-auto max-w-2xl px-4 py-5 sm:px-6">
				<!-- Mark all read can't ride along in the mobile header: the title is
				     centered and each side slot caps at 35% of the width, which the
				     preferences icon already takes. It shares the filter row instead —
				     the tabs don't fill the width, so both fit on one line and the
				     button costs no vertical space. -->
				<div class="mb-4 flex items-center justify-between gap-2">
					<TabButtons v-model="filter" :options="FILTERS" />
					<Button
						v-if="unread > 0"
						class="sm:hidden"
						variant="subtle"
						size="md"
						label="Mark all read"
						@click="markAllAsRead"
					/>
				</div>

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
	</div>
</template>
