<script setup lang="ts">
import { Button, LoadingText, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { shortDate } from '@/lib/date'
import { type DunningTone, getDunningSteps } from '@/lib/dunning'
import { formatDate, money } from '@/lib/format'
import { walletCoverPercent } from '@/lib/spendShare'
import { __ } from '@/lib/translate'

interface Props {
	outstanding: number
	walletActive: boolean
}

const props = defineProps<Props>()

defineEmits<{ openSchedule: []; openWallet: []; addCredit: [] }>()

const { nextPayment, credit, forecast, methods, currency, reloadMethods } =
	useBillingOverview()

const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const loading = computed(
	() =>
		(nextPayment.loading && !nextPayment.data) ||
		(credit.loading && !credit.data),
)

const hasOutstanding = computed(() => props.outstanding > 0)
const nextCharge = computed(() => Number(nextPayment.data?.amount ?? 0))
const blocker = computed(() =>
	nextCharge.value > 0 ? nextPayment.data?.blockers?.[0] : undefined,
)
const nextPaymentOn = computed(() => shortDate(nextPayment.data?.charge_on))
const nextPaymentFailed = computed(() =>
	Boolean(nextPayment.error && !nextPayment.data),
)

// A missed bill's place on the dunning ladder, shown under "Due now".
const dunningSteps = computed(() =>
	hasOutstanding.value ? getDunningSteps(nextPayment.data) : [],
)

const dunningToneClass: Record<DunningTone, string> = {
	neutral: 'text-ink-gray-9',
	warning: 'text-ink-amber-6',
	danger: 'text-ink-red-7',
}

// The row describes this cycle's charge; a due-now bill carries its own warning.
const cycleBlocker = computed(() =>
	hasOutstanding.value ? undefined : blocker.value,
)

const paymentHint = computed(() => {
	if (hasOutstanding.value) return ''
	if (cycleBlocker.value) return cycleBlocker.value.title

	const method = nextPayment.data?.method?.label

	return method ? `Charged to ${method}` : ''
})

const balance = computed(() => Number(credit.data?.balance ?? 0))
const projected = computed(() => Number(forecast.data?.projected_total ?? 0))

const workingMethod = computed(() =>
	(methods.data ?? []).find((method) => method.status === 'Active'),
)

// What the card or UPI is left with after the wallet, drawn as the bill draws it, so
// GST already paid with top-ups counts.
const shortfall = computed(() => Number(forecast.data?.shortfall ?? 0))
// The shortfall is measured against what is collected, which is less than the total under TDS.
const collectable = computed(() =>
	Number(forecast.data?.expected_collection ?? 0),
)

const short = computed(() => projected.value > 0 && shortfall.value > 0)

const atRisk = computed(() => short.value && !workingMethod.value)

const coverage = computed(() => {
	if (!projected.value) return ''
	if (!short.value) return __('Covers this cycle in full')

	const percent = walletCoverPercent(collectable.value, shortfall.value)

	return atRisk.value
		? __('Covers {0}% of this cycle', [percent])
		: __('Covers {0}% of this cycle, card pays the rest', [percent])
})

const expiry = computed(() => {
	const grant = credit.data?.expiring?.[0]

	if (!grant) return ''

	const amount = money(grant.amount, currency.value)

	return `${amount} expires ${formatDate(grant.expires_on)}`
})

const walletHint = computed(() =>
	[coverage.value, expiry.value].filter(Boolean).join('. '),
)

const primaryMethod = computed(() => workingMethod.value ?? methods.data?.[0])
const nextInvoiceOn = computed(() => shortDate(forecast.data?.period_end))

const showAddMethod = ref(false)

const onAddMethod = () => {
	if (requireSetup()) showAddMethod.value = true
}
</script>

<template>
	<div
		class="grid grid-cols-[minmax(0,1fr)_auto] content-between items-center gap-x-3 gap-y-3 px-4 py-3 text-base leading-6"
	>
		<LoadingText v-if="loading" :lines="4" class="col-span-2 py-2" />

		<template v-else>
			<template v-if="hasOutstanding">
				<span class="truncate text-ink-gray-5"> {{ __('Due now') }} </span>

				<div class="flex items-center justify-end gap-2">
					<Tooltip :text="blocker?.title" :disabled="!blocker">
						<span
							class="whitespace-nowrap text-base-medium tabular-nums text-ink-gray-9"
						>
							{{ money(outstanding, currency) }}
						</span>
					</Tooltip>
				</div>
			</template>

			<template v-for="step in dunningSteps" :key="step.label">
				<span class="truncate text-ink-gray-5"> {{ step.label }} </span>

				<div class="flex items-center justify-end gap-2">
					<Tooltip :text="step.hint">
						<span
							class="whitespace-nowrap text-base-medium tabular-nums"
							:class="dunningToneClass[step.tone]"
						>
							{{ shortDate(step.date) }}
						</span>
					</Tooltip>
				</div>
			</template>

			<span class="truncate text-ink-gray-5"> {{ __('Wallet') }} </span>

			<div class="flex items-center justify-end gap-2">
				<Tooltip :text="__('Wallet history')">
					<Button
						variant="ghost"
						size="xs"
						icon="lucide-history"
						:label="__('Wallet history')"
						:disabled="walletActive"
						@click="$emit('openWallet')"
					/>
				</Tooltip>

				<Button
					v-if="canManageBilling"
					size="xs"
					:label="__('Add credit')"
					@click="$emit('addCredit')"
				/>

				<Tooltip :text="walletHint" :disabled="!walletHint">
					<span
						class="whitespace-nowrap text-base-medium tabular-nums text-ink-gray-9"
					>
						{{ money(balance, currency) }}
					</span>
				</Tooltip>
			</div>

			<span class="truncate text-ink-gray-5"> {{ __('Payment method') }} </span>

			<span
				v-if="primaryMethod"
				class="truncate text-right text-base-medium text-ink-gray-9"
			>
				{{ primaryMethod.display_label || primaryMethod.method_type }}
			</span>
			<Button
				v-else-if="canManageBilling"
				class="justify-self-end"
				size="xs"
				:label="__('Add card')"
				@click="onAddMethod"
			/>
			<span v-else class="text-right text-ink-gray-5">{{ __('None') }}</span>

			<span class="truncate text-ink-gray-5"> {{ __('Next invoice') }} </span>

			<span
				class="whitespace-nowrap text-right text-base-medium tabular-nums text-ink-gray-9"
			>
				{{ nextInvoiceOn || '—' }}
			</span>

			<span class="truncate text-ink-gray-5">
				{{ __('Next payment date') }}
			</span>

			<div class="flex items-center justify-end gap-2">
				<Tooltip v-if="canManageBilling" :text="__('Change payment date')">
					<Button
						variant="ghost"
						size="xs"
						icon="lucide-calendar-cog"
						:label="__('Change payment date')"
						@click="$emit('openSchedule')"
					/>
				</Tooltip>
				<template v-if="nextPaymentFailed">
					<span class="whitespace-nowrap text-ink-red-6"
						>{{ __("Couldn't load") }}</span
					>
					<Button
						size="xs"
						:label="__('Retry')"
						@click="nextPayment.reload()"
					/>
				</template>
				<Tooltip v-else :text="paymentHint" :disabled="!paymentHint">
					<span
						class="whitespace-nowrap text-base-medium tabular-nums"
						:class="cycleBlocker ? 'text-ink-amber-6' : 'text-ink-gray-9'"
					>
						{{ nextPaymentOn || '—' }}
					</span>
				</Tooltip>
			</div>
		</template>

		<AddMethodDialog v-model="showAddMethod" @done="reloadMethods" />
	</div>
</template>
