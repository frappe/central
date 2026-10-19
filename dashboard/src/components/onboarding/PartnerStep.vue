<script setup lang="ts">
import {
	Alert,
	Avatar,
	Button,
	LoadingText,
	TextInput,
	useCall,
} from 'frappe-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import ChoiceCards, { type Choice } from '@/components/common/ChoiceCards.vue'
import PartnerPayerChoice from '@/components/partner/PartnerPayerChoice.vue'
import PartnerTeamPicker from '@/components/partner/PartnerTeamPicker.vue'
import { usePartnerRequests } from '@/composables/usePartnerRequests'
import type { PartnerPayer } from '@/composables/usePartnerSetup'
import { getErrorMessage, successToast } from '@/lib/feedback'

defineEmits<{ submit: [] }>()

const { requests, accept, reload } = usePartnerRequests()
const loading = ref(true)
const chosenTeam = ref<string | null>(null)
const payer = ref<PartnerPayer>('customer')
const access = ref<'yes' | 'later'>('yes')
const naming = ref(false)
const teamName = ref('')
const saving = ref(false)
const accepted = ref(false)
const error = ref('')

// Called directly: useCreateTeam switches to the new team, which reloads the console.
const createTeamCall = useCall<{ name: string }, { team_name: string }>({
	url: method(API.createTeam),
	method: 'POST',
	immediate: false,
})

const request = computed(() => requests.value[0] ?? null)
const partnerName = computed(() => request.value?.partner_name ?? '')
const chosen = computed(
	() =>
		request.value?.teams.find((team) => team.name === chosenTeam.value) ?? null,
)
const accessChoices = computed<Choice[]>(() => [
	{
		label: 'Yes',
		value: 'yes',
		description: 'Partner role: run servers, see bills.',
	},
	{
		label: 'Not now',
		value: 'later',
		description: 'Give it later in Settings.',
	},
])
const accessNote = computed(() =>
	payer.value === 'partner'
		? `${partnerName.value} pays, so they get the Partner role: they can run your servers and manage this account's billing.`
		: '',
)

// Reload, so a team created in the step before is offered too.
onMounted(async () => {
	await reload()
	loading.value = false
})

watch(
	request,
	(current) => {
		if (current?.teams.some((t) => t.name === chosenTeam.value && t.available))
			return
		chosenTeam.value =
			current?.teams.find((team) => team.available)?.name ?? null
	},
	{ immediate: true },
)

async function createTeam(): Promise<void> {
	if (!teamName.value.trim()) return
	saving.value = true
	error.value = ''
	try {
		const team = await createTeamCall.submit({
			team_name: teamName.value.trim(),
		})
		if (createTeamCall.error || !team) throw createTeamCall.error
		await reload()
		chosenTeam.value = team.name
		naming.value = false
	} catch (exception) {
		error.value = getErrorMessage(
			exception,
			"We couldn't create the account. Try again.",
		)
	} finally {
		saving.value = false
	}
}

async function submit(): Promise<boolean> {
	if (accepted.value || !request.value) return true
	if (!chosen.value?.available) return false

	saving.value = true
	error.value = ''
	try {
		await accept(request.value.name, {
			team: chosen.value.name,
			paidByPartner: payer.value === 'partner',
			partnerAccess: access.value === 'yes',
		})
		accepted.value = true
		successToast(`${partnerName.value} now works with ${chosen.value.label}.`)
		return true
	} catch (exception) {
		error.value = getErrorMessage(
			exception,
			"We couldn't save your answer. Try again.",
		)
		return false
	} finally {
		saving.value = false
	}
}

defineExpose({
	canSubmit: computed(
		() =>
			!loading.value &&
			!naming.value &&
			(accepted.value || !request.value || Boolean(chosen.value?.available)),
	),
	submitLabel: 'Continue',
	saving,
	submit,
})
</script>

<template>
	<LoadingText v-if="loading" text="Loading" />

	<p v-else-if="!request" class="text-p-base text-ink-gray-7">
		No partner is waiting for your answer.
	</p>

	<div v-else class="space-y-5">
		<Alert v-if="error" theme="red" :title="error" />

		<div class="flex items-center gap-3">
			<Avatar
				:image="request.logo ?? undefined"
				:label="request.partner_name"
				size="2xl"
				shape="square"
			/>
			<div>
				<p class="text-base font-medium text-ink-gray-8">
					{{ request.partner_name }}
				</p>
				<p class="text-p-sm text-ink-gray-5">For {{ request.project_title }}</p>
			</div>
		</div>

		<div v-if="naming" class="space-y-2">
			<TextInput
				v-model="teamName"
				label="Account name"
				size="md"
				placeholder="e.g. Northwind"
				autofocus
				@keyup.enter="createTeam"
			/>
			<div class="flex gap-2">
				<Button
					variant="solid"
					label="Create account"
					:loading="saving"
					:disabled="!teamName.trim()"
					@click="createTeam"
				/>
				<Button label="Back" :disabled="saving" @click="naming = false" />
			</div>
		</div>

		<PartnerTeamPicker
			v-else
			v-model="chosenTeam"
			:teams="request.teams"
			:partner-name="request.partner_name"
			@create="naming = true"
		/>

		<PartnerPayerChoice
			v-model="payer"
			:partner-name="request.partner_name"
			:partner-description="`${request.partner_name} pays Frappe Cloud for this account.`"
			:disabled="saving"
		/>

		<p v-if="accessNote" class="text-p-sm text-ink-gray-6">{{ accessNote }}</p>
		<div v-else class="space-y-2">
			<p class="text-base font-medium text-ink-gray-8">
				Give {{ request.partner_name }} access to your servers?
			</p>
			<ChoiceCards
				:model-value="access"
				:options="accessChoices"
				:columns="2"
				:label="`Give ${request.partner_name} access to your servers?`"
				:disabled="saving"
				@update:model-value="access = $event === 'later' ? 'later' : 'yes'"
			/>
		</div>
	</div>
</template>
