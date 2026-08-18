<script setup lang="ts">
import { Button, LoadingText, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { formatDate, money } from '@/lib/format'
import { infoToast } from '@/lib/toast'

// Wallet — the FC v2 prototype's funding card: balance, a one-line coverage
// verdict, and (once there's a method to charge) the funding actions. The chevron
// / title open the wallet-history slide-over the page owns; Add credit tops up
// right here.
defineProps<{ active?: boolean }>()
defineEmits<{ open: [] }>()
const { credit, forecast, methods, currency, reloadMoney } =
	useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const balance = computed(() => Number(credit.data?.balance ?? 0))
const projected = computed(() => Number(forecast.data?.projected_total ?? 0))
const loading = computed(() => credit.loading && !credit.data)

// Coverage verdict, mirroring the prototype's three states. The wallet is prepaid
// and a working card covers any shortfall, so "at risk" only when the balance is
// short AND nothing can be charged behind it.
const hasMethod = computed(() => (methods.data?.length ?? 0) > 0)
const hasWorkingMethod = computed(() =>
	(methods.data ?? []).some((m) => m.status === 'Active'),
)
const short = computed(
	() => projected.value > 0 && balance.value < projected.value,
)
const atRisk = computed(() => short.value && !hasWorkingMethod.value)

// How far the balance goes against this cycle. A bare "card covers the rest" says
// nothing about how much rest there is; a percentage is the same sentence with the
// number the customer would otherwise have to work out.
const coverPct = computed(() => {
	if (projected.value <= 0) return null
	return Math.min(100, Math.floor((balance.value / projected.value) * 100))
})

// Promotional credit on a clock. Only the soonest grant is named on the card —
// the rest are in the wallet history — since the date the customer needs to act on
// is the first one.
const nextExpiry = computed(() => credit.data?.expiring?.[0])

const showTopup = ref(false)
function onAddCredit(): void {
	if (requireSetup()) showTopup.value = true
}

// GROUNDING GAP (#69): no auto-recharge endpoint yet, so the button answers
// with the same notice as the wallet panel's toggle.
function onAutoRecharge(): void {
	infoToast("Auto-recharge isn't available yet")
}
</script>

<template>
	<div
		class="flex flex-col rounded-6 border bg-surface-base p-5 transition-colors"
		:class="active ? 'border-outline-gray-4' : 'border-outline-gray-2'"
	>
		<div class="flex h-6 items-center justify-between gap-2">
			<span class="flex items-center gap-1">
				<button
					type="button"
					class="text-p-sm text-ink-gray-5 transition-colors hover:text-ink-gray-7"
					@click="$emit('open')"
				>
					Wallet
				</button>
				<Tooltip text="Pays invoices before your card is charged">
					<span
						class="lucide-info size-3.5 text-ink-gray-4"
						aria-hidden="true"
					/>
				</Tooltip>
			</span>
			<button
				type="button"
				class="grid size-6 place-items-center rounded-4 text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-gray-6"
				aria-label="Open wallet history"
				@click="$emit('open')"
			>
				<span class="lucide-chevron-right size-4" aria-hidden="true" />
			</button>
		</div>

		<div v-if="loading" class="mt-2 w-32">
			<LoadingText :lines="1" />
		</div>
		<template v-else>
			<p class="mt-1.5 text-2xl-semibold tabular-nums text-ink-gray-9">
				{{ money(balance, currency) }}
			</p>
			<!-- Coverage verdict — always the third line -->
			<p
				v-if="atRisk"
				class="mt-1.5 flex items-center gap-1.5 text-p-sm text-ink-red-6"
			>
				<span
					class="lucide-triangle-alert size-3.5 shrink-0"
					aria-hidden="true"
				/>
				<template v-if="coverPct != null">
					Covers {{ coverPct }}% of this cycle
				</template>
				<template v-else>Insufficient balance</template>
			</p>
			<p
				v-else-if="short"
				class="mt-1.5 flex items-center gap-1.5 text-p-sm text-ink-gray-5"
			>
				<span
					class="lucide-credit-card size-3.5 shrink-0 text-ink-gray-4"
					aria-hidden="true"
				/>
				<template v-if="coverPct != null">
					Covers {{ coverPct }}% of this cycle · card covers the rest
				</template>
				<template v-else>Card covers the rest</template>
			</p>
			<p v-else class="mt-1.5 text-p-sm text-ink-gray-5">
				<!-- An empty wallet with nothing owed is a wallet with no credit in it;
				     saying "nothing due this cycle" describes the cycle instead, which
				     is the neighbouring card's job. -->
				<template v-if="projected > 0">Covers this cycle in full</template>
				<template v-else-if="balance > 0"
					>Ready for your first invoice</template
				>
				<template v-else>No credit added yet</template>
			</p>

			<!-- Free credit runs out; purchased credit doesn't. Say so before it does. -->
			<p
				v-if="nextExpiry"
				class="mt-1.5 flex items-center gap-1.5 text-p-sm text-ink-gray-5"
			>
				<span
					class="lucide-clock size-3.5 shrink-0 text-ink-gray-4"
					aria-hidden="true"
				/>
				{{ money(nextExpiry.amount, currency) }}
				expires
				{{ formatDate(nextExpiry.expires_on) }}
			</p>

			<!-- Funding actions, once there's a method to charge. -->
			<div
				v-if="hasMethod && canManageBilling"
				class="mt-auto flex items-center justify-between gap-2 pt-4"
			>
				<Button
					variant="ghost"
					size="sm"
					label="Auto-recharge off"
					class="-ml-2"
					@click="onAutoRecharge"
				>
					<template #prefix
						><span class="lucide-zap size-4" aria-hidden="true" /></template
					>
				</Button>
				<Button
					variant="subtle"
					size="sm"
					label="Add credit"
					@click="onAddCredit"
				>
					<template #prefix
						><span class="lucide-plus size-4" aria-hidden="true" /></template
					>
				</Button>
			</div>
		</template>

		<TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
	</div>
</template>
