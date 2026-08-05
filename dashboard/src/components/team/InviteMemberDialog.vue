<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import CapabilityList from '@/components/team/CapabilityList.vue'
import { useSession } from '@/composables/useSession'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { errorToast, successToast } from '@/lib/toast'
import type { CapabilityInfo } from '@/types/api'

// Invite a person to the active team with a role. The role picker excludes Owner
// (invitations can never grant Owner — Transfer Ownership does that) and shows a
// live preview of exactly what the chosen role will let them do.
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [v: boolean]; invited: [] }>()

const { activeTeam } = useSession()
const { roles, capabilities, capsByRole } = useTeamRoles()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

const email = ref('')
const role = ref('')
const expiresInDays = ref(7)

const roleOptions = computed(() =>
	roles.value
		.filter((r) => r.role_name !== 'Owner')
		.map((r) => ({ label: r.role_name, value: r.name })),
)

const previewCaps = computed<string[]>(() =>
	role.value ? (capsByRole.value[role.value] ?? []) : [],
)
const palette = computed<CapabilityInfo[]>(() => capabilities.value)

// Reset the form each time the dialog opens.
watch(open, (isOpen) => {
	if (isOpen) {
		email.value = ''
		role.value = ''
		expiresInDays.value = 7
	}
})

type InviteParams = {
	team: string
	email: string
	role: string
	expires_in_days: number
}
const inviteCall = useCall<string, InviteParams>({
	url: method(API.inviteTeamMember),
	method: 'POST',
	immediate: false,
})

const canSubmit = computed(
	() => /\S+@\S+\.\S+/.test(email.value) && !!role.value,
)

const dialogOptions = computed(() => ({
	title: 'Invite member',
	size: 'xl' as const,
	actions: [
		{
			label: 'Send invite',
			variant: 'solid' as const,
			loading: inviteCall.loading,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))

async function submit() {
	if (!canSubmit.value) return
	try {
		await inviteCall.submit({
			team: activeTeam.value!,
			email: email.value.trim().toLowerCase(),
			role: role.value,
			expires_in_days: expiresInDays.value,
		})
		if (inviteCall.error) throw inviteCall.error
		successToast(`Invitation sent to ${email.value.trim().toLowerCase()}.`)
		emit('invited')
		open.value = false
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:size="dialogOptions.size"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<div class="space-y-4">
				<FormControl
					v-model="email"
					type="email"
					label="Email"
					placeholder="person@example.com"
					autocomplete="off"
				/>
				<FormControl
					v-model="role"
					type="select"
					label="Role"
					:options="roleOptions"
					placeholder="Choose a role"
				/>
				<FormControl
					v-model.number="expiresInDays"
					type="number"
					label="Invitation expires in (days)"
					:min="1"
					:max="30"
				/>

				<div
					v-if="role"
					class="max-h-[40vh] overflow-y-auto rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3"
				>
					<p class="mb-3 text-p-sm font-medium text-ink-gray-7">
						This role can:
					</p>
					<CapabilityList :caps="previewCaps" :palette="palette" />
				</div>
			</div>
		</template>
	</Dialog>
</template>
