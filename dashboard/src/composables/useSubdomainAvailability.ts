import { frappeRequest } from 'frappe-ui'
import { onScopeDispose, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { SubdomainAvailability } from '@/types/serverCreation'

/** Whether a site name is free, checked while the user types it. */
export function useSubdomainAvailability(subdomain: Ref<string>) {
	const { activeTeam } = useSession()
	const availability = ref<SubdomainAvailability | null>(null)
	const checking = ref(false)
	const error = ref('')
	let debounce: ReturnType<typeof setTimeout> | undefined

	watch(subdomain, (value) => {
		availability.value = null
		error.value = ''
		clearTimeout(debounce)
		const name = value.trim()
		checking.value = !!name
		if (name) debounce = setTimeout(() => check(name), 400)
	})

	// The debounce timer outlives the component if the user navigates away mid-type.
	onScopeDispose(() => clearTimeout(debounce))

	async function check(name: string) {
		try {
			const result = await frappeRequest<SubdomainAvailability>({
				url: methodV1(API.checkSubdomain),
				method: 'GET',
				params: { subdomain: name, team: activeTeam.value },
			})
			// A newer name is in flight and owns the result.
			if (name !== subdomain.value.trim()) return
			availability.value = result
		} catch (failure) {
			if (name !== subdomain.value.trim()) return
			error.value = getErrorMessage(failure, 'Could not check that name.')
		} finally {
			if (name === subdomain.value.trim()) checking.value = false
		}
	}

	return { availability, checking, error }
}
