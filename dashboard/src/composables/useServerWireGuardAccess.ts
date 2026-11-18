import { useCall } from 'frappe-ui'
import { computed, type Ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { reportError } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'

/** Turns WireGuard device access on or off for one server. */
export function useServerWireGuardAccess(resourceId: Ref<string>) {
	const { activeTeam } = useSession()

	const accessCall = useCall<
		null,
		{ team: string; resource_id: string; enabled: boolean }
	>({
		url: method(API.setServerWireguardAccess),
		method: 'POST',
		immediate: false,
	})

	async function setWireGuardAccess(enabled: boolean): Promise<boolean> {
		if (!activeTeam.value) return false

		try {
			await submitOrThrow(accessCall, {
				team: activeTeam.value,
				resource_id: resourceId.value,
				enabled,
			})
			return true
		} catch (error) {
			reportError(error, { title: "WireGuard VPN wasn't changed" })
			return false
		}
	}

	return {
		setWireGuardAccess,
		isSavingAccess: computed(() => accessCall.loading),
	}
}
