import { useCall } from 'frappe-ui'
import { computed, type Ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { reportError } from '@/lib/feedback'

/** Turns termination protection on or off for one server. */
export function useTerminationProtection(resourceId: Ref<string>) {
	const { activeTeam } = useSession()

	const protectionCall = useCall<
		null,
		{ team: string; resource_id: string; enabled: boolean }
	>({
		url: method(API.setTerminationProtection),
		method: 'POST',
		immediate: false,
	})

	async function setTerminationProtection(enabled: boolean): Promise<boolean> {
		if (!activeTeam.value) return false

		try {
			await protectionCall.submit({
				team: activeTeam.value,
				resource_id: resourceId.value,
				enabled,
			})
			return true
		} catch (error) {
			reportError(error, { title: "Termination protection wasn't changed" })
			return false
		}
	}

	return {
		setTerminationProtection,
		isSavingProtection: computed(() => protectionCall.loading),
	}
}
