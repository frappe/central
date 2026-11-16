<script setup lang="ts">
import { Avatar, Dialog, ErrorMessage, FormControl, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { addPartner, findPartner } from '@/composables/usePartnerLinks'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { PartnerLink, PartnerPreview } from '@/types/api'

interface AddPartnerDialogProps {
	/** The code from a Frappe Connect link. */
	initialCode?: string
	/** The Partner Customer ID from a Frappe Connect link. */
	reference?: string | null
}

const props = defineProps<AddPartnerDialogProps>()
const emit = defineEmits<{ added: [link: PartnerLink] }>()
const open = defineModel<boolean>('open', { default: false })

const session = useSession()
const code = ref('')
const team = ref('')
const partner = ref<PartnerPreview | null>(null)
const checking = ref(false)
const adding = ref(false)
const error = ref('')

// A team that already has a partner ends that link first, so it is not offered.
const teamOptions = computed(() =>
	session.teams.value
		.filter((option) => option.status === 'Active' && !option.has_partner)
		.map((option) => ({ label: option.label, value: option.name })),
)

watch(open, (isOpen) => {
	if (!isOpen) return
	code.value = props.initialCode ?? ''
	team.value = session.activeTeam.value ?? ''
	partner.value = null
	error.value = ''
	if (code.value) checkCode()
})

// A customer who signed up from a Connect link has no team yet. Onboarding creates it.
watch(session.activeTeam, (active) => {
	if (!open.value || team.value || !active) return
	team.value = active
	if (code.value) checkCode()
})

watch(code, () => {
	partner.value = null
})

async function checkCode(): Promise<void> {
	if (!code.value.trim() || !team.value) return
	checking.value = true
	error.value = ''
	try {
		partner.value = await findPartner(team.value, code.value.trim())
	} catch (failure) {
		error.value = getErrorMessage(failure, "We couldn't check this code.")
	} finally {
		checking.value = false
	}
}

async function submit(): Promise<void> {
	if (!partner.value) return checkCode()
	adding.value = true
	error.value = ''
	try {
		const link = await addPartner(
			team.value,
			code.value.trim(),
			props.reference ?? null,
		)
		await session.reload()
		session.setActiveTeam(team.value)
		open.value = false
		emit('added', link)
	} catch (failure) {
		error.value = getErrorMessage(failure, "We couldn't add the partner.")
	} finally {
		adding.value = false
	}
}

const actions = computed(() => [
	{
		label: partner.value ? __('Add partner') : __('Check code'),
		variant: 'solid' as const,
		loading: checking.value || adding.value,
		disabled: !code.value.trim() || !team.value,
		onClick: submit,
	},
])
</script>

<template>
	<Dialog
		v-model="open"
		:title="__('Add partner')"
		size="sm"
		:actions="actions"
	>
		<div class="space-y-4">
			<FormControl
				v-if="teamOptions.length > 1"
				v-model="team"
				type="select"
				size="md"
				:label="__('Team')"
				:options="teamOptions"
			/>
			<TextInput
				v-model="code"
				size="md"
				:label="__('Partner code')"
				:placeholder="__('e.g. TRI-48213')"
				autocomplete="off"
				autofocus
				@blur="checkCode"
				@keyup.enter="submit"
			/>
			<div
				v-if="partner"
				class="flex items-center gap-2 rounded-6 bg-surface-gray-2 p-3"
			>
				<Avatar
					:image="partner.partner_logo ?? undefined"
					:label="partner.partner_name"
					size="lg"
					shape="square"
				/>
				<p class="text-base-medium text-ink-gray-8">
					{{ partner.partner_name }}
				</p>
			</div>
			<ErrorMessage v-if="error" :message="error" />
		</div>
	</Dialog>
</template>
