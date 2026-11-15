<script setup lang="ts">
import {
	Avatar,
	Button,
	ErrorMessage,
	FormControl,
	LoadingText,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import AddPartnerDialog from '@/components/partners/AddPartnerDialog.vue'
import EndPartnerLinkDialog from '@/components/partners/EndPartnerLinkDialog.vue'
import PayerChangeDialog, {
	type PayerChange,
} from '@/components/partners/PayerChangeDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useOnboarding } from '@/composables/useOnboarding'
import {
	isPartnerPaying,
	nextPayerChangeDay,
	setPartnerRole,
	usePartnerLinkIntent,
	useTeamPartner,
} from '@/composables/usePartnerLinks'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { formatDate } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { PartnerLink, PartnerRole } from '@/types/api'

const session = useSession()
const intent = usePartnerLinkIntent()
const { pendingSteps } = useOnboarding()
const { canManagePartners } = useCapabilities()
const { link, loading, error, reload } = useTeamPartner()

const adding = ref(false)
const ending = ref<PartnerLink | null>(null)

// A Connect link for a team still in onboarding adds the partner there. A team that has
// finished onboarding gets the dialog here.
const isLinkWaiting = computed(() => {
	const team = session.teams.value.find(
		(option) => option.name === session.activeTeam.value,
	)
	return (
		Boolean(intent.code.value) &&
		Boolean(team) &&
		!team?.has_partner &&
		!pendingSteps.value.length
	)
})
watch(
	isLinkWaiting,
	(isWaiting) => {
		if (isWaiting) adding.value = true
	},
	{ immediate: true },
)
watch(adding, (isOpen) => {
	if (!isOpen && intent.code.value) intent.clear()
})

const roleOptions = [
	{ label: __('Viewer'), value: 'Viewer' },
	{ label: __('Developer'), value: 'Developer' },
]
const roleHint = computed(() =>
	link.value?.role === 'Developer'
		? __(
				'Your partner can create, change and delete servers. They cannot manage members or billing.',
			)
		: __(
				'Your partner can see your servers and sites, and cannot change them.',
			),
)
const payerChange = ref<PayerChange | null>(null)
const startDay = computed(() => formatDate(nextPayerChangeDay()))

const payerText = computed(() => {
	const current = link.value
	if (!current) return ''
	const partner = current.partner_name
	const currency = current.partner_currency
	if (current.payer === 'Partner Requested')
		return __('You asked {0} to pay. They have not answered yet.', [partner])
	if (current.payer === 'Partner')
		return isPartnerPaying(current)
			? __('{0} pays for your usage, in {1}.', [partner, currency])
			: __('{0} pays for your usage from {1}, in {2}.', [
					partner,
					formatDate(current.partner_pays_from),
					currency,
				])
	if (isPartnerPaying(current))
		return __('{0} pays until {1}. You pay from the next day.', [
			partner,
			formatDate(current.partner_pays_until),
		])
	return __('You pay for your usage.')
})

// The one change the customer can make now, with the words they confirm.
const payerAction = computed<PayerChange | null>(() => {
	const current = link.value
	if (!current) return null
	const partner = current.partner_name
	if (current.payer === 'Customer')
		return {
			link: current.name,
			payer: 'Partner Requested',
			title: __('Ask {0} to pay', [partner]),
			message: __(
				'If {0} accepts, it pays for your usage from {1}. From then, your prices show and are charged in {2}, its currency.',
				[partner, startDay.value, current.partner_currency],
			),
			confirmLabel: __('Ask {0} to pay', [partner]),
		}
	if (current.payer === 'Partner Requested')
		return {
			link: current.name,
			payer: 'Customer',
			title: __('Withdraw the request'),
			message: __('You keep paying for your usage.'),
			confirmLabel: __('Withdraw request'),
		}
	return {
		link: current.name,
		payer: 'Customer',
		title: __('Pay for your own usage'),
		message: isPartnerPaying(current)
			? __('You pay for your usage from {0}, in your own currency.', [
					startDay.value,
				])
			: __('{0} will not start paying.', [partner]),
		confirmLabel: __('Pay myself'),
		isDestructive: true,
	}
})

const savingRole = ref(false)
const roleError = ref('')

async function changeRole(role: PartnerRole): Promise<void> {
	if (!link.value || role === link.value.role) return
	savingRole.value = true
	roleError.value = ''
	try {
		await setPartnerRole(link.value.name, role)
		await reload()
		successToast(__('Access changed to {0}', [role]))
	} catch (failure) {
		roleError.value = getErrorMessage(failure, "We couldn't change the access.")
	} finally {
		savingRole.value = false
	}
}

function onChanged(): void {
	session.reload()
	reload()
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<main class="mx-auto flex max-w-3xl flex-col gap-4 p-3 md:p-4 lg:mt-6">
			<div>
				<h1 class="text-lg-semibold text-ink-gray-9">{{ __('Partner') }}</h1>
				<p class="mt-0.5 text-p-base text-ink-gray-5">
					{{ __('The Frappe partner that works with your team.') }}
				</p>
			</div>

			<LoadingText v-if="loading && !link" :text="__('Loading partner')" />

			<div v-else-if="error" class="space-y-3">
				<ErrorMessage :message="error" />
				<Button :label="__('Try again')" @click="reload" />
			</div>

			<template v-else-if="link">
				<div
					class="flex items-center gap-3 rounded-6 border border-outline-gray-2 p-4"
				>
					<Avatar
						:image="link.partner_logo ?? undefined"
						:label="link.partner_name"
						size="2xl"
						shape="square"
					/>
					<div class="min-w-0 flex-1">
						<p class="truncate text-base-medium text-ink-gray-9">
							{{ link.partner_name }}
						</p>
						<p class="mt-0.5 text-p-sm text-ink-gray-5">
							{{ __('Partner since {0}', [formatDate(link.linked_on)]) }}
						</p>
					</div>
					<Button
						v-if="canManagePartners"
						theme="red"
						:label="__('End link')"
						@click="ending = link"
					/>
				</div>

				<div class="rounded-6 border border-outline-gray-2 p-4">
					<FormControl
						type="select"
						size="md"
						:label="__('Access')"
						:options="roleOptions"
						:model-value="link.role"
						:disabled="!canManagePartners || savingRole"
						@update:model-value="changeRole"
					/>
					<p class="mt-1.5 text-p-sm text-ink-gray-5">{{ roleHint }}</p>
					<ErrorMessage v-if="roleError" class="mt-2" :message="roleError" />
				</div>

				<div
					class="flex flex-wrap items-center justify-between gap-3 rounded-6 border border-outline-gray-2 p-4"
				>
					<div class="min-w-0">
						<p class="text-base-medium text-ink-gray-8">{{ __('Who pays') }}</p>
						<p class="mt-0.5 text-p-sm text-ink-gray-5">{{ payerText }}</p>
					</div>
					<Button
						v-if="canManagePartners && payerAction"
						:label="payerAction.confirmLabel"
						@click="payerChange = payerAction"
					/>
				</div>
			</template>

			<EmptyState
				v-else
				icon="lucide-handshake"
				:title="__('No partner yet')"
				:description="__('A Frappe partner can build and run your systems. Add one with the code they gave you.')"
			>
				<template v-if="canManagePartners" #action>
					<Button
						variant="solid"
						:label="__('Add partner')"
						@click="adding = true"
					/>
				</template>
			</EmptyState>
		</main>

		<AddPartnerDialog
			v-model:open="adding"
			:initial-code="intent.code.value"
			:reference="intent.reference.value"
			@added="onChanged"
		/>
		<PayerChangeDialog v-model:target="payerChange" @changed="onChanged" />
		<EndPartnerLinkDialog
			v-model:target="ending"
			:other-team-name="link?.partner_name ?? ''"
			@ended="onChanged"
		/>
	</div>
</template>
