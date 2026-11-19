import { useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { getErrorMessage, isAbortError } from '@/lib/feedback'

interface GitHubInstallation {
	installation_id: string
	account: string
	account_type: 'User' | 'Organization'
	avatar_url: string
}

interface GitHubRepository {
	repository_id: string
	full_name: string
	private: boolean
	is_admin: boolean
}

interface ConnectionAttempt {
	is_expired: boolean
	return_url: string | null
	server: string
	team: string
	is_authorized: boolean
	authorize_url: string
	install_url: string
	installations: GitHubInstallation[]
	granted_repository_ids: string[]
}

/** One Pilot's request to connect GitHub: authorize, pick an account, then grant repositories. */
export function useGitHubConnection(attempt: string) {
	const installationId = ref('')
	/** Selected repository IDs per opened account. Unopened accounts keep their grant. */
	const selections = ref<Record<string, Set<string>>>({})
	const initialSelections: Record<string, Set<string>> = {}
	const busy = ref(false)
	const error = ref('')

	const attemptCall = useCall<ConnectionAttempt, { attempt: string }>({
		url: method(API.getGitHubConnectionAttempt),
		params: { attempt },
	})
	const repositoriesCall = useCall<
		GitHubRepository[],
		{ attempt: string; installation_id: string }
	>({
		url: method(API.getGitHubInstallationRepositories),
		immediate: false,
	})
	const completeCall = useCall<
		{ return_url: string },
		{ attempt: string; grants: Record<string, string[]> }
	>({
		url: method(API.completeGitHubConnection),
		method: 'POST',
		immediate: false,
	})

	const connection = computed(() => attemptCall.data ?? null)
	const installations = computed(() => connection.value?.installations ?? [])
	const repositories = computed(() => repositoriesCall.data ?? [])
	const selected = computed(
		() => selections.value[installationId.value] ?? new Set<string>(),
	)
	const selectedCount = computed(() =>
		Object.values(selections.value).reduce((count, ids) => count + ids.size, 0),
	)
	const hasChanges = computed(() =>
		Object.entries(selections.value).some(([id, ids]) => {
			const initial = initialSelections[id]
			return (
				ids.size !== initial.size ||
				[...ids].some((repositoryId) => !initial.has(repositoryId))
			)
		}),
	)

	watch(installations, (items) => {
		if (!installationId.value && items.length)
			installationId.value = items[0].installation_id
	})

	watch(installationId, async (value) => {
		if (!value) return
		const loaded = await repositoriesCall
			.submit({ attempt, installation_id: value })
			.catch(() => null)
		// The page shows a load error. An account that did not load keeps its grant.
		if (!loaded || repositoriesCall.error) return
		// A first visit starts from the current grant.
		if (value !== installationId.value || selections.value[value]) return
		const granted = new Set(connection.value?.granted_repository_ids ?? [])
		initialSelections[value] = new Set(
			repositories.value
				.filter(
					(repository) =>
						repository.is_admin && granted.has(repository.repository_id),
				)
				.map((repository) => repository.repository_id),
		)
		selections.value[value] = new Set(initialSelections[value])
	})

	function toggle(repositoryId: string) {
		const next = new Set(selected.value)
		if (next.has(repositoryId)) next.delete(repositoryId)
		else next.add(repositoryId)
		selections.value[installationId.value] = next
	}

	function detach() {
		selections.value[installationId.value] = new Set()
	}

	async function grant() {
		busy.value = true
		error.value = ''
		const result = await completeCall
			.submit({
				attempt,
				grants: Object.fromEntries(
					Object.entries(selections.value).map(([id, ids]) => [id, [...ids]]),
				),
			})
			.catch(() => null)
		if (!result || completeCall.error) {
			error.value = getErrorMessage(
				completeCall.error,
				"We couldn't connect GitHub.",
			)
			busy.value = false
			return
		}
		window.location.assign(result.return_url)
	}

	return {
		connection,
		loading: computed(() => attemptCall.loading && !connection.value),
		loadError: computed(() =>
			attemptCall.error
				? getErrorMessage(attemptCall.error, 'This link is not valid.')
				: '',
		),
		installations,
		installationId,
		repositories,
		repositoriesLoading: computed(() => repositoriesCall.loading),
		repositoriesError: computed(() =>
			repositoriesCall.error && !isAbortError(repositoriesCall.error)
				? getErrorMessage(repositoriesCall.error)
				: '',
		),
		selections,
		selected,
		selectedCount,
		hasChanges,
		toggle,
		detach,
		grant,
		busy,
		error,
	}
}
