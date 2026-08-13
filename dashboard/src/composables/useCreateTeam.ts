import { computed, ref } from 'vue'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'

// Naming and creating a team, shared by the two places that offer it: the
// servers page's dialog and the Teams tab of settings. The rule that a name
// must be unique among your teams lives here so both can't drift apart on it.
export function useCreateTeam() {
	const { saving, createTeam } = useTeamSettings()
	const { teams } = useSession()

	const teamName = ref('')
	const name = computed(() => teamName.value.trim())

	// Duplicate names are legal, but a switcher of identical rows is unusable —
	// so say so before the team exists rather than after.
	const duplicate = computed(() =>
		teams.value.some(
			(team) => team.label.toLowerCase() === name.value.toLowerCase(),
		),
	)
	const canSubmit = computed(() => name.value.length > 0 && !duplicate.value)

	// A logo can't be set yet: the upload endpoint lands in a follow-up PR, so
	// the picker beside the name is present but inert.

	const reset = (): void => {
		teamName.value = ''
	}

	// Resolves true once the team exists; useTeamSettings.createTeam switches to
	// it and re-pulls the session.
	const submit = async (): Promise<boolean> => {
		if (!canSubmit.value) return false
		if (!(await createTeam(name.value))) return false
		reset()
		return true
	}

	return { teamName, name, duplicate, canSubmit, saving, submit, reset }
}
