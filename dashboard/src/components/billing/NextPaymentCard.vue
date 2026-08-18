<script setup lang="ts">
import { Alert, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { shortDate } from '@/lib/date'
import { money } from '@/lib/format'

// Next payment — when we will charge, how much, and from which instrument. The
// card exists for its third line: where the team's own state already decides the
// debit cannot go through (no active method, a bill over the silent-debit ceiling,
// a mandate ceiling below the invoice), it says so BEFORE the 1st rather than
// after a failed charge. CollectionActionBanner only appears once the team is
// already in Action Required, which is too late to be useful.
//
// An empty blocker list is never rendered as "this will work" — nothing can know
// that. It renders as what we intend to do.
defineProps<{ active?: boolean }>()
defineEmits<{ open: [] }>()
const { nextPayment, currency } = useBillingOverview()

const loading = computed(() => nextPayment.loading && !nextPayment.data)
const np = computed(() => nextPayment.data)
const amount = computed(() => Number(np.value?.amount ?? 0))
const blocker = computed(() => np.value?.blockers?.[0])
const chargeOn = computed(() => shortDate(np.value?.charge_on))

const instrument = computed(() => {
	const method = np.value?.method
	if (method?.label) return `from ${method.label}`
	if (np.value?.collection_mode === 'Prepaid') return 'from your wallet'
	return null
})
</script>

<template>
	<div
		class="flex flex-col rounded-6 border bg-surface-base p-5 transition-colors"
		:class="active ? 'border-outline-gray-4' : 'border-outline-gray-2'"
	>
		<div class="flex h-6 items-center justify-between gap-2">
			<!-- With nothing due there is no schedule to show, so the card does not
			     pretend to be a door. -->
			<button
				v-if="amount > 0"
				type="button"
				class="text-p-sm text-ink-gray-5 transition-colors hover:text-ink-gray-7"
				@click="$emit('open')"
			>
				Next payment
			</button>
			<span v-else class="text-p-sm text-ink-gray-5">Next payment</span>
			<button
				v-if="amount > 0"
				type="button"
				class="grid size-6 place-items-center rounded-4 text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-gray-6"
				aria-label="Open payment schedule"
				@click="$emit('open')"
			>
				<span class="lucide-chevron-right size-4" aria-hidden="true" />
			</button>
		</div>

		<div v-if="loading" class="mt-2 w-32">
			<LoadingText :lines="1" />
		</div>

		<template v-else-if="amount > 0">
			<p class="mt-1.5 text-2xl-semibold tabular-nums text-ink-gray-9">
				{{ chargeOn || '—' }}
			</p>
			<p class="mt-1.5 text-p-sm text-ink-gray-5">
				{{ money(amount, currency) }}<template v-if="instrument"> ·
					{{ instrument }}</template>
			</p>

			<!-- The reason the card is here. Only ever shown where the data entails
			     it — never as a guess about whether a card will work. -->
			<Alert v-if="blocker" class="mt-3" theme="amber" :title="blocker.title" />
			<p
				v-else
				class="mt-1.5 flex items-center gap-1.5 text-p-sm text-ink-gray-5"
			>
				<span
					class="lucide-check size-3.5 shrink-0 text-ink-gray-4"
					aria-hidden="true"
				/>
				We'll charge this automatically
			</p>
		</template>

		<template v-else>
			<p class="mt-1.5 text-2xl-semibold tabular-nums text-ink-gray-9">
				{{ money(0, currency) }}
			</p>
			<p class="mt-1.5 text-p-sm text-ink-gray-5">
				Nothing to pay yet — we'll bill on the 1st for whatever you run.
			</p>
		</template>
	</div>
</template>
