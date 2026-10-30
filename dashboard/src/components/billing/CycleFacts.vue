<script setup lang="ts">
import { Button, LoadingText, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { shortDate } from '@/lib/date'
import { formatDate, money } from '@/lib/format'

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

const amountDue = computed(() =>
	hasOutstanding.value ? props.outstanding : nextCharge.value,
)

const blocker = computed(() =>
	nextCharge.value > 0 ? nextPayment.data?.blockers?.[0] : undefined,
)

const dueHint = computed(() => {
	if (blocker.value) return blocker.value.title
	if (hasOutstanding.value || !nextCharge.value) return ''

	const chargedOn = `Charged ${shortDate(nextPayment.data?.charge_on)}`
	const method = nextPayment.data?.method?.label

	return method ? `${chargedOn} from ${method}` : chargedOn
})

const balance = computed(() => Number(credit.data?.balance ?? 0))
const projected = computed(() => Number(forecast.data?.projected_total ?? 0))

const workingMethod = computed(() =>
	(methods.data ?? []).find((method) => method.status === 'Active'),
)

const short = computed(
	() => projected.value > 0 && balance.value < projected.value,
)

const atRisk = computed(() => short.value && !workingMethod.value)

const coverage = computed(() => {
	if (!projected.value) return ''
	if (!short.value) return 'Covers this cycle in full'

	const percent = Math.floor((balance.value / projected.value) * 100)
	const covers = `Covers ${percent}% of this cycle`

	return atRisk.value ? covers : `${covers}, card pays the rest`
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
		class="grid grid-cols-[auto_minmax(0,1fr)] content-between items-center gap-x-3 gap-y-3 px-4 py-3 text-base leading-6"
	>
		<LoadingText v-if="loading" :lines="4" class="col-span-2 py-2" />

		<template v-else>
			<span class="whitespace-nowrap text-ink-gray-5">
				{{ hasOutstanding ? 'Due now' : 'Next payment' }}
			</span>

			<div class="flex items-center justify-end gap-2">
				<Button
					v-if="nextCharge > 0"
					size="xs"
					label="Schedule"
					icon-left="lucide-calendar-clock"
					@click="$emit('openSchedule')"
				/>

				<Tooltip :text="dueHint" :disabled="!dueHint">
					<span
						class="whitespace-nowrap text-base-medium tabular-nums text-ink-gray-9"
					>
						{{ money(amountDue, currency) }}
					</span>
				</Tooltip>
			</div>

			<span class="whitespace-nowrap text-ink-gray-5"> Wallet </span>

			<div class="flex items-center justify-end gap-2">
				<Tooltip text="Wallet history">
					<Button
						variant="ghost"
						size="xs"
						icon="lucide-history"
						label="Wallet history"
						:disabled="walletActive"
						@click="$emit('openWallet')"
					/>
				</Tooltip>

				<Button
					v-if="canManageBilling"
					size="xs"
					label="Add credit"
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

			<span class="whitespace-nowrap text-ink-gray-5"> Payment method </span>

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
				label="Add card"
				@click="onAddMethod"
			/>
			<span v-else class="text-right text-ink-gray-5">None</span>

			<span class="whitespace-nowrap text-ink-gray-5"> Next invoice </span>

			<span
				class="whitespace-nowrap text-right text-base-medium tabular-nums text-ink-gray-9"
			>
				{{ nextInvoiceOn || '—' }}
			</span>
		</template>

		<AddMethodDialog v-model="showAddMethod" @done="reloadMethods" />
	</div>
</template>
