import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import type { MeteredServices } from '@/types/billing'

const { activeTeam } = useSession()
const meteredCall = useCall<MeteredServices, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => meteredCall.reload())

export function useMeteredServices() {
	return {
		metered: meteredCall,
		services: computed(() => meteredCall.data?.services ?? []),
		availablePlans: computed(() => meteredCall.data?.available_plans ?? []),
		currency: computed(() => meteredCall.data?.currency ?? 'USD'),
		loading: computed(() => meteredCall.loading && !meteredCall.data),
		reload: () => meteredCall.reload(),
	}
}
