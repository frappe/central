import { useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { teamParams } from '@/composables/useTeamScope'
import { emailError } from '@/lib/auth'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type { ResourceType } from '@/types/api'

/** The resource key a row holds when its invitation covers the whole team. */
export const ALL_RESOURCES = '*::'

export interface InviteRow {
	email: string
	role: string
	/** `*::` for the whole team, or `Server::<name>` / `Site::<name>`. */
	resource: string
	/** The server's answer for this row, shown under it. */
	error: string
}

/** The most people one request may invite. Mirrors MAX_INVITATIONS_PER_REQUEST in team.py. */
export const MAX_INVITATIONS = 10

type InvitationRequest = {
	email: string
	role: string
	resource_type: ResourceType
	resource_name: string | null
}
type InvitationResult = {
	email: string
	invitation: string | null
	error: string | null
}

// Rows of email, role and resource, sent in one request as one invitation each. The onboarding
// invite step and the team page's invite dialog share it, so both keep one rule
// for the default role, the button label, and what happens when a row fails.
export function useBulkInvite() {
	const { roles, loading, error: rolesError } = useTeamRoles()

	const inviteCall = useCall<
		InvitationResult[],
		{ team: string; invitations: InvitationRequest[] }
	>({
		url: method(API.inviteTeamMember),
		method: 'POST',
		immediate: false,
	})

	const rows = ref<InviteRow[]>([])
	const saving = ref(false)
	// A refusal of the whole request, such as a missing permission. Row refusals sit on their row.
	const requestError = ref('')

	// Owner is granted by transfer, never by invitation.
	const roleOptions = computed(() =>
		roles.value
			.filter((role) => role.role_name !== 'Owner')
			.map((role) => ({ label: role.role_name, value: role.name })),
	)
	const defaultRole = computed(
		() =>
			roleOptions.value.find((option) => option.label === 'Developer')?.value ??
			roleOptions.value[0]?.value ??
			'',
	)
	watch(
		defaultRole,
		(role) => {
			for (const row of rows.value) row.role ||= role
		},
		{ immediate: true },
	)

	const filledRows = computed(() =>
		rows.value.filter((row) => row.email.trim()),
	)
	const canSubmit = computed(
		() =>
			filledRows.value.length > 0 && filledRows.value.every((row) => row.role),
	)
	const submitLabel = computed(() => {
		const count = filledRows.value.length
		if (!count) return 'Send invitations'
		return `Send ${count} ${count === 1 ? 'invitation' : 'invitations'}`
	})

	function newRow(): InviteRow {
		return {
			email: '',
			role: defaultRole.value,
			resource: ALL_RESOURCES,
			error: '',
		}
	}

	function reset(): void {
		rows.value = [newRow()]
		requestError.value = ''
	}

	// The server invites each row on its own, so one refusal does not stop the others.
	// The rows that were sent leave the list, so a second try sends only the failed ones.
	async function submit(): Promise<{ sent: number; failed: number }> {
		requestError.value = ''
		for (const row of filledRows.value) row.error = emailError(row.email)
		const valid = filledRows.value.filter((row) => !row.error)
		const invalid = filledRows.value.filter((row) => row.error)

		saving.value = true
		const refused = valid.length ? await sendInvitations(valid) : []
		saving.value = false

		const failed = [...invalid, ...refused]
		const sent = valid.length - refused.length
		if (sent)
			successToast(
				sent === 1 ? 'Invitation sent' : `Invitations sent to ${sent} people`,
			)
		rows.value = failed.length ? failed : [newRow()]
		return { sent, failed: failed.length }
	}

	// Resolves to the rows the server refused, each with its error message.
	async function sendInvitations(batch: InviteRow[]): Promise<InviteRow[]> {
		try {
			await submitOrThrow(inviteCall, {
				...teamParams(),
				invitations: batch.map(toInvitationRequest),
			})
		} catch (exception) {
			requestError.value = getErrorMessage(
				exception,
				"The invitations couldn't be sent.",
			)
			return batch
		}

		const results = inviteCall.data ?? []
		return batch.filter((row, index) => {
			row.error = results[index]?.error ?? ''
			return Boolean(row.error)
		})
	}

	reset()

	return {
		rows,
		roleOptions,
		defaultRole,
		rolesLoading: loading,
		rolesError,
		canSubmit,
		submitLabel,
		saving,
		requestError,
		reset,
		submit,
	}
}

function toInvitationRequest(row: InviteRow): InvitationRequest {
	const [resourceType, resourceName] = row.resource.split('::') as [
		ResourceType,
		string,
	]
	return {
		email: row.email.trim().toLowerCase(),
		role: row.role,
		resource_type: resourceType,
		resource_name: resourceName || null,
	}
}
