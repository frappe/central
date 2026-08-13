import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useFrappeEventListener } from '@/composables/useFrappeRealtime'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import type { NotificationFeed, TeamNotification } from '@/types/billing'

const PAGE_SIZE = 20

const { activeTeam } = useSession()

const start = ref(0)
const loaded = ref<TeamNotification[]>([])
const unreadCount = ref(0)
const hasMore = ref(false)

const feedCall = useCall<
	NotificationFeed,
	{ team: string; start: number; limit: number }
>({
	url: method(API.notifications),
	params: () => ({ ...teamParams(), start: start.value, limit: PAGE_SIZE }),
	immediate: false,
	refetch: true,
	onSuccess: (data: NotificationFeed) => {
		if (start.value === 0) {
			loaded.value = data.items
		} else {
			const seen = new Set(loaded.value.map((item) => item.name))
			loaded.value = [
				...loaded.value,
				...data.items.filter((item) => !seen.has(item.name)),
			]
		}
		unreadCount.value = data.unread
		hasMore.value = data.has_next_page
	},
})

const markRead = useCall<{ unread: number }, { team: string; name: string }>({
	url: method(API.markNotificationRead),
	method: 'POST',
	immediate: false,
})
const markAll = useCall<{ unread: number }, { team: string }>({
	url: method(API.markAllNotificationsRead),
	method: 'POST',
	immediate: false,
})

const refresh = (): void => {
	start.value = 0
	feedCall.reload()
}

whenTeamReady(refresh)

export const useNotificationsRealtime = (): void => {
	useFrappeEventListener<{ team: string }>(
		() => (activeTeam.value ? `team_notification:${activeTeam.value}` : ''),
		refresh,
	)
}

export const useNotifications = () => {
	return {
		items: computed<TeamNotification[]>(() => loaded.value),
		unread: computed(() => unreadCount.value),
		hasNextPage: computed(() => hasMore.value),
		loading: computed(() => feedCall.loading),
		refresh,
		loadMore: async (): Promise<void> => {
			if (!hasMore.value || feedCall.loading) return
			start.value += PAGE_SIZE
			await feedCall.reload()
		},
		markAsRead: async (name: string): Promise<void> => {
			const row = loaded.value.find((item) => item.name === name)
			if (!row || row.is_read) return
			row.is_read = 1
			const response = await markRead.submit({ ...teamParams(), name })
			unreadCount.value = response?.unread ?? Math.max(0, unreadCount.value - 1)
		},
		markAllAsRead: async (): Promise<void> => {
			await markAll.submit(teamParams())
			for (const item of loaded.value) item.is_read = 1
			unreadCount.value = 0
		},
	}
}
