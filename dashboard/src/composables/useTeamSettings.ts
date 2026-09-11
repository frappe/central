import { dialog, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'
import type { Team } from '@/types/api'

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
const leaveCall = useCall<{ left: boolean }, { team: string }>({
	url: method(API.leaveTeam),
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
			'Team renamed',
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
			`${user} is now the owner`,
		)
	}

	function deleteTeam(team?: string) {
		return run(
			deleteCall,
			{ team: team ?? activeTeam.value! },
			async () => {
				await session.reload()
				session.setActiveTeam(session.teams.value[0]?.name ?? null)
				caps.reload()
			},
			'Team deleted',
		)
	}

	const leaveTeam = (team: string) => {
		return run(
			leaveCall,
			{ team },
			async () => {
				await session.reload()
				if (activeTeam.value === team) {
					session.setActiveTeam(session.teams.value[0]?.name ?? null)
				}
				caps.reload()
			},
			'You left the team',
		)
	}

	const teamColumns = [
		{ key: 'label', label: 'Name', class: 'w-full' },
		{ key: 'role', label: 'Role' },
		{ key: 'members', label: 'Members' },
		{ key: 'created', label: 'Created' },
		{ key: 'actions', label: '', class: 'w-10' },
	]

	const confirmLeave = (team: Team): void => {
		dialog.danger({
			title: 'Leave team',
			message: `You'll lose access to everything in “${team.label}”. An admin can invite you back.`,
			confirmLabel: 'Leave team',
			onConfirm: async () => {
				await leaveTeam(team.name)
			},
		})
	}

	const explainOwnerCantLeave = (team: Team): void => {
		dialog.confirm({
			title: 'Transfer ownership first',
			message: `You own “${team.label}”. Hand it to another member before you leave, or delete the team.`,
			confirmLabel: 'Got it',
		})
	}

	const teamRowActions = (team: Team) => {
		const owned = team.owner === currentUser.value
		return [
			{
				label: 'Switch team',
				icon: 'lucide-repeat',
				condition: () => team.name !== activeTeam.value,
				onClick: () => session.setActiveTeam(team.name),
			},
			{
				label: 'Leave team',
				icon: 'lucide-log-out',
				theme: 'red' as const,
				onClick: () =>
					owned ? explainOwnerCantLeave(team) : confirmLeave(team),
			},
		]
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
			`Created “${teamName}”`,
		)
	}

	return {
		isOwner,
		saving: computed(() => saving.value),
		rename,
		transferOwnership,
		deleteTeam,
		leaveTeam,
		teamColumns,
		teamRowActions,
		createTeam,
	}
}
