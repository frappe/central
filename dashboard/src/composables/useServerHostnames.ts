import { frappeRequest } from 'frappe-ui'
import { type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'

export interface ServerHostname {
	hostname: string
	kind: 'Site' | 'Custom domain'
}

// The sites and custom domains a server answers, read when a server is picked. A late
// reply for a server the user already moved away from is dropped.
export function useServerHostnames(server: Ref<VirtualMachineRow | null>) {
	const { activeTeam } = useSession()
	const hostnames = ref<ServerHostname[]>([])
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		hostnames.value = []
		error.value = ''
		const resourceId = server.value?.resource_id
		if (!resourceId || !activeTeam.value) return

		loading.value = true
		try {
			const rows = await frappeRequest<ServerHostname[]>({
				url: methodV1(API.serverHostnames),
				method: 'GET',
				params: { team: activeTeam.value, resource_id: resourceId },
			})
			if (current === generation) hostnames.value = rows
		} catch (e) {
			if (current === generation)
				error.value = getErrorMessage(e, "We couldn't list its sites.")
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch(server, reload, { immediate: true })
	return { hostnames, loading, error }
}
