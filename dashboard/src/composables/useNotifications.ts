import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useSession } from '@/composables/useSession'
import { useFrappeEventListener } from '@/composables/common/useFrappeRealtime'
import type { NotificationFeed, TeamNotification } from '@/types/billing'

// The team's unified in-app notification feed (billing + server). A module
// singleton — the topbar bell and the /notifications page read the same data, so a
// mark-read in one reflects in the other. Re-pulls on team switch, and refreshes
// live off the team-namespaced `team_notification:<team>` realtime nudge.

const { activeTeam } = useSession()

const feedCall = useCall<NotificationFeed, { team: string; limit: number }>({
	url: method(API.notifications),
	params: () => ({ ...teamParams(), limit: 100 }),
	immediate: false,
	refetch: true,
})

const markRead = useCall<{ unread: number }, { name: string }>({
	url: method(API.markNotificationRead),
	method: 'POST',
	immediate: false,
})
const markAll = useCall<{ unread: number }, Record<string, never>>({
	url: method(API.markAllNotificationsRead),
	method: 'POST',
	immediate: false,
})

whenTeamReady(() => feedCall.reload())

// Live badge: the writer emits `team_notification:<team>` (payload just the team).
// Must run inside a component setup() (it needs the socket off the component
// instance), so it can't live at module scope — AppShell calls this once on mount.
export function useNotificationsRealtime(): void {
	useFrappeEventListener<{ team: string }>(
		() => (activeTeam.value ? `team_notification:${activeTeam.value}` : ''),
		() => feedCall.reload(),
	)
}

const items = computed<TeamNotification[]>(() => feedCall.data?.items ?? [])
const unread = computed(() => feedCall.data?.unread ?? 0)

export function useNotifications() {
	return {
		items,
		unread,
		loading: computed(() => feedCall.loading),
		reload: () => feedCall.reload(),
		async markAsRead(name: string): Promise<void> {
			await markRead.submit({ name, ...teamParams() })
			await feedCall.reload()
		},
		async markAllAsRead(): Promise<void> {
			await markAll.submit({ ...teamParams() })
			await feedCall.reload()
		},
	}
}
