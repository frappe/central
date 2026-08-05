import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'

// Team-level mutations for the active team: rename (team:edit), transfer ownership
// (current owner only), delete (team:delete), and create a new team. Each re-pulls
// the session (team list / labels) and capabilities so the switcher and every gate
// reflect the change immediately.
const renameCall = useCall<
	{ team_name: string },
	{ team: string; team_name: string }
>({
	url: method(API.renameTeam),
	method: 'POST',
	immediate: false,
})
const transferCall = useCall<{ owner: string }, { team: string; user: string }>(
	{
		url: method(API.transferOwnership),
		method: 'POST',
		immediate: false,
	},
)
const deleteCall = useCall<{ deleted: boolean }, { team: string }>({
	url: method(API.deleteTeam),
	method: 'POST',
	immediate: false,
})
const createCall = useCall<{ name: string }, { team_name: string }>({
	url: method(API.createTeam),
	method: 'POST',
	immediate: false,
})

export function useTeamSettings() {
	const session = useSession()
	const caps = useCapabilities()
	const { currentUser } = useAuth()
	const saving = ref(false)
	const activeTeam = session.activeTeam

	const isOwner = computed(
		() =>
			session.teams.value.find((t) => t.name === activeTeam.value)?.owner ===
			currentUser.value,
	)

	async function run<T>(
		call: { submit: (p: T) => Promise<unknown>; error: unknown },
		params: T,
		onDone: () => unknown,
		ok: string,
	): Promise<boolean> {
		saving.value = true
		try {
			await call.submit(params)
			if (call.error) throw call.error
			successToast(ok)
			await onDone()
			return true
		} catch (e) {
			errorToast(e)
			return false
		} finally {
			saving.value = false
		}
	}

	function rename(teamName: string) {
		return run(
			renameCall,
			{ team: activeTeam.value!, team_name: teamName },
			() => session.reload(),
			'Team renamed.',
		)
	}

	function transferOwnership(user: string) {
		return run(
			transferCall,
			{ team: activeTeam.value!, user },
			async () => {
				await session.reload()
				caps.reload()
			},
			`${user} is now the owner.`,
		)
	}

	function deleteTeam() {
		return run(
			deleteCall,
			{ team: activeTeam.value! },
			async () => {
				await session.reload()
				session.setActiveTeam(session.teams.value[0]?.name ?? null)
				caps.reload()
			},
			'Team deleted.',
		)
	}

	function createTeam(teamName: string) {
		return run(
			createCall,
			{ team_name: teamName },
			async () => {
				await session.reload()
				if (createCall.data?.name) session.setActiveTeam(createCall.data.name)
				caps.reload()
			},
			`Created “${teamName}”.`,
		)
	}

	return {
		isOwner,
		saving: computed(() => saving.value),
		rename,
		transferOwnership,
		deleteTeam,
		createTeam,
	}
}
