import { ref, computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import type { NotificationCategory } from '@/types/billing'

export interface NotificationPreference {
	category: NotificationCategory
	email_enabled: boolean
	in_app_enabled: boolean
}

const CATEGORIES: NotificationCategory[] = ['Billing', 'Server', 'Team']

function defaults(): NotificationPreference[] {
	return CATEGORIES.map((category) => ({
		category,
		email_enabled: true,
		in_app_enabled: true,
	}))
}

const getCall = useCall<{ preferences: { category: string; email_enabled: number; in_app_enabled: number }[] }>({
	url: method(API.getNotificationPreferences),
	params: () => ({ ...teamParams() }),
	immediate: false,
	refetch: true,
})

const saveCall = useCall<{ saved: boolean; preferences: unknown[] }, { team: string; preferences: { category: string; email_enabled: number; in_app_enabled: number }[] }>({
	url: method(API.saveNotificationPreferences),
	method: 'POST',
	immediate: false,
})

whenTeamReady(() => getCall.reload())

const preferences = computed<NotificationPreference[]>(() => {
	if (!getCall.data?.preferences?.length) return defaults()
	return getCall.data.preferences.map((p) => ({
		category: p.category as NotificationCategory,
		email_enabled: !!p.email_enabled,
		in_app_enabled: !!p.in_app_enabled,
	}))
})

const saving = computed(() => saveCall.loading)

export function useNotificationPreferences() {
	return {
		preferences,
		loading: computed(() => getCall.loading),
		saving,
		async save(prefs: NotificationPreference[]): Promise<void> {
			const { activeTeam } = await import('@/composables/useSession').then((m) => m.useSession())
			await saveCall.submit({
				team: activeTeam.value!,
				preferences: prefs.map((p) => ({
					category: p.category,
					email_enabled: p.email_enabled ? 1 : 0,
					in_app_enabled: p.in_app_enabled ? 1 : 0,
				})),
			})
			if (saveCall.error) throw saveCall.error
			await getCall.reload()
		},
	}
}
