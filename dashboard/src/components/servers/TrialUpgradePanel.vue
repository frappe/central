<script setup lang="ts">
import { Alert, call, Radio, RadioGroup } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API } from '@/api/methods'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import { formatDate, money, plural } from '@/lib/format'
import type { ServerTrial, TrialPlanChoice } from '@/types/billing'

interface Props {
	trial: ServerTrial
	/** The paid plans the site may move to, cheapest first. */
	plans: TrialPlanChoice[]
	checking: boolean
	serverId: string
}

const props = defineProps<Props>()
const emit = defineEmits<{ check: [] }>()

const { requireSetup, setupDialogOpen } = useBillingSetup()
const { activeTeam } = useSession()
const showAddMethod = ref(false)
// A new card is confirmed by the gateway first, so the trial can stay open for a moment.
const methodAdded = ref(false)

const selected = ref(props.trial.plan?.name ?? props.plans[0]?.name ?? '')
const choice = computed(() =>
	props.plans.find((plan) => plan.name === selected.value),
)
const price = computed(() =>
	choice.value
		? money(choice.value.monthly_rate, choice.value.currency, {
				trimTrailingZeros: true,
			})
		: '',
)

const title = computed(() =>
	props.trial.state === 'Ended'
		? 'Your free trial has ended'
		: `Your free trial ends in ${plural(props.trial.days_left, 'day')}`,
)

const description = computed(() => {
	if (props.trial.state !== 'Ended' || !props.trial.deletes_on)
		return 'Choose a plan to keep this site after the trial. Billing starts when you add a payment method.'
	const deletesOn = formatDate(props.trial.deletes_on)
	return props.trial.can_keep
		? `This site is stopped. Choose a plan and keep the site before ${deletesOn}.`
		: `This site is stopped. Choose a plan and add a payment method before ${deletesOn} to keep it.`
})

const facts = computed(() => [
	{
		icon: 'lucide-credit-card',
		text: `Billing starts at ${price.value} a month when your site moves to this plan.`,
	},
	{
		icon: 'lucide-terminal',
		text: 'Every plan gives you full server access: SSH, the web console, Pilot and snapshots.',
	},
	{
		icon: 'lucide-refresh-cw',
		text: 'Your site restarts once, for a few minutes, to move to the new plan. Its data stays as it is.',
	},
])

const saving = ref(false)
const actionError = ref<string | null>(null)

// Central keeps the choice, so the conversion moves the site to it whichever way it starts.
async function run(action: () => Promise<unknown>): Promise<void> {
	saving.value = true
	actionError.value = null
	try {
		await call(API.resizeServer, {
			team: activeTeam.value,
			resource_id: props.serverId,
			plan: selected.value,
		})
		await action()
	} catch (error) {
		actionError.value = getErrorMessage(error)
	} finally {
		saving.value = false
	}
}

const addMethod = () =>
	run(async () => {
		if (requireSetup()) showAddMethod.value = true
	})

const choosePlan = () => run(async () => emit('check'))

const keep = () =>
	run(async () => {
		await call(API.keepTrialSite, {
			team: activeTeam.value,
			resource_id: props.serverId,
		})
		emit('check')
	})

function onMethodAdded(): void {
	methodAdded.value = true
	emit('check')
}

const canContinue = computed(() => Boolean(choice.value) && !saving.value)

// The dialog's footer holds the button, so it reads these.
defineExpose({ addMethod, choosePlan, keep, methodAdded, saving, canContinue })
</script>

<template>
	<div class="space-y-4">
		<Alert
			:theme="trial.state === 'Ended' ? 'red' : 'blue'"
			:title="title"
			:description="description"
		/>
		<Alert
			v-if="trial.held"
			theme="amber"
			title="This site stays on its free trial"
			description="Your payment method is added, but this plan is above your spending limit. Choose a smaller plan, or contact support to raise the limit."
		/>
		<Alert
			v-if="actionError"
			theme="red"
			title="Couldn't save your plan"
			:description="actionError"
		/>

		<p v-if="!plans.length" class="text-p-sm text-ink-gray-6">
			No plan fits your spending limit. Contact support to raise it.
		</p>
		<RadioGroup
			v-else
			v-model="selected"
			aria-label="Plans"
			:disabled="saving || methodAdded"
		>
			<div
				v-for="plan in plans"
				:key="plan.name"
				class="flex items-center gap-3 rounded-6 border px-4 py-3"
				:class="
					selected === plan.name
						? 'border-outline-gray-5'
						: 'border-outline-gray-2'
				"
			>
				<Radio
					class="min-w-0 flex-1"
					:value="plan.name"
					:label="plan.title"
					:description="plan.specs"
				/>
				<span class="shrink-0 text-p-base-medium tabular-nums text-ink-gray-9">
					{{ money(plan.monthly_rate, plan.currency, { trimTrailingZeros: true }) }}/mo
				</span>
			</div>
		</RadioGroup>

		<ul v-if="choice" class="space-y-3">
			<li
				v-for="fact in facts"
				:key="fact.icon"
				class="flex items-start gap-3 text-p-sm text-ink-gray-7"
			>
				<span
					:class="fact.icon"
					class="mt-0.5 size-4 shrink-0 text-ink-gray-5"
					aria-hidden="true"
				/>
				{{ fact.text }}
			</li>
		</ul>

		<p v-if="methodAdded" class="text-p-sm text-ink-gray-6" aria-live="polite">
			We are confirming your payment method. This can take a minute.
		</p>

		<AddMethodDialog v-model="showAddMethod" @done="onMethodAdded" />
		<EditBillingProfileDialog v-model="setupDialogOpen" />
	</div>
</template>
