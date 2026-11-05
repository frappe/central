import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { FirewallChange } from '@/lib/firewall'

/** Each server's error, or null when it changed. */
export type FirewallResults = Record<string, string | null>

/** Changes the firewall of one or more servers. */
export function useServerFirewall() {
	const { activeTeam } = useSession()

	const networkCall = useCall<
		FirewallResults,
		{ team: string; resource_ids: string[]; firewall: FirewallChange }
	>({
		url: method(API.updateServerFirewall),
		method: 'POST',
		immediate: false,
	})

	// A request-wide failure, such as an invalid rule, returns the same error for every server.
	async function updateFirewall(
		resourceIds: string[],
		firewall: FirewallChange,
	): Promise<FirewallResults> {
		if (!activeTeam.value) return {}

		await networkCall.submit({
			team: activeTeam.value,
			resource_ids: resourceIds,
			firewall,
		})
		if (!networkCall.error) return networkCall.data ?? {}

		const message = getErrorMessage(
			networkCall.error,
			"The firewall couldn't be changed.",
		)
		return Object.fromEntries(resourceIds.map((id) => [id, message]))
	}

	return { updateFirewall, isSaving: computed(() => networkCall.loading) }
}
