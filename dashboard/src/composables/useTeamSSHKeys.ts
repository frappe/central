import { call, frappeRequest } from 'frappe-ui'
import { ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { TeamSSHKey } from '@/types/sshKeys'

export function useTeamSSHKeys() {
	const { activeTeam } = useSession()
	const keys = ref<TeamSSHKey[]>([])
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		keys.value = []
		error.value = ''
		if (!activeTeam.value) {
			loading.value = false
			return
		}
		loading.value = true
		try {
			const rows = await frappeRequest<TeamSSHKey[]>({
				url: methodV1(API.listTeamSSHKeys),
				method: 'GET',
				params: { team: activeTeam.value },
			})
			if (current === generation) keys.value = rows
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(failure, "SSH keys couldn't be loaded.")
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch(activeTeam, reload, { immediate: true })

	async function create(title: string, publicKey: string): Promise<TeamSSHKey> {
		const key = await call<TeamSSHKey>(API.createTeamSSHKey, {
			team: activeTeam.value,
			title,
			public_key: publicKey,
		})
		await reload()
		return key
	}

	async function rotate(name: string, publicKey: string) {
		await call(API.rotateTeamSSHKey, {
			team: activeTeam.value,
			name,
			public_key: publicKey,
		})
		await reload()
	}

	async function retry(name: string) {
		await call(API.retryTeamSSHKeySync, { team: activeTeam.value, name })
	}

	async function remove(name: string) {
		await call(API.deleteTeamSSHKey, { team: activeTeam.value, name })
		await reload()
	}

	return { keys, loading, error, reload, create, rotate, retry, remove }
}
