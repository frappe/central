<script setup lang="ts">
import {
	Badge,
	Button,
	LoadingText,
	PageHeaderBackButton,
	PageHeaderMobile,
	Spinner,
} from 'frappe-ui'
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import InvoiceReceipt from '@/components/billing/InvoiceReceipt.vue'
import { INVOICES_PATH, useInvoiceDetail } from '@/composables/useInvoiceDetail'
import { useInvoices } from '@/composables/useInvoices'
import { useIsMobile } from '@/composables/useIsMobile'
import { billingPeriod, shortDate } from '@/lib/date'
import { money } from '@/lib/format'
import { invoiceTheme } from '@/lib/status'
import { isAbortError } from '@/lib/toast'

// One invoice receipt as a full page. A phone has no room for the 24rem panel
// the Invoices page docks beside its list, so a row pushes this instead and Back
// goes where you'd expect. Same body, different chrome.
const route = useRoute()
const router = useRouter()
const isMobile = useIsMobile()
const { reload: reloadInvoices } = useInvoices()

const name = computed(() => String(route.params.name ?? ''))
const { detail, isOverdue, settling, canPay, payBusy, pay } = useInvoiceDetail(
	name,
	{ onPaid: reloadInvoices },
)

// The number is the one piece of identity the header can hold. The route already
// names it, so it's there before the fetch lands and the header never opens empty.
const title = computed(() => detail.data?.name || name.value)

watch(
	isMobile,
	(mobile) => {
		// Widened past the breakpoint (a resize, a rotate): this invoice has a panel
		// to live in now, so follow it across. `?invoice=` is how the list is asked
		// to open a receipt it wasn't clicked into — the same door global search uses.
		if (!mobile)
			router.replace({ path: INVOICES_PATH, query: { invoice: name.value } })
	},
	{ immediate: true },
)

// A name nothing comes back for (a stale link, an invoice from another team)
// belongs back at the list rather than on a blank page. An aborted read isn't a
// failure — a team switch supersedes the one in flight.
watch(
	() => detail.error,
	(error) => {
		if (error && !isAbortError(error)) router.replace(INVOICES_PATH)
	},
)
</script>

<template>
	<!-- No desktop PageHeader and no `sm:hidden`: the watcher above hands this
	     route over to the list's docked panel the moment it isn't mobile, so the
	     page never renders at desktop width. -->
	<PageHeaderMobile :title="title">
		<template #prefix>
			<PageHeaderBackButton :to="INVOICES_PATH" />
		</template>
		<!-- The panel's header actions, in the header a page has. GROUNDING GAP
		     (#70): no email-invoice / download-PDF endpoints yet, so both stay
		     disabled until the backend lands them. -->
		<template #suffix>
			<Button
				variant="ghost"
				icon="lucide-mail"
				:disabled="true"
				title="Email invoice — coming soon"
				label="Email invoice"
			/>
			<Button
				variant="ghost"
				icon="lucide-download"
				:disabled="true"
				title="Download PDF — coming soon"
				label="Download PDF"
			/>
		</template>
	</PageHeaderMobile>

	<div v-if="detail.loading && !detail.data" class="space-y-3 p-4">
		<LoadingText :lines="6" />
	</div>

	<div v-else-if="detail.data" class="mx-auto w-full max-w-3xl pb-5">
		<!-- The rest of the identity the panel carries in its header. The mobile
		     header centers its title between two 35%-wide slots, so only the number
		     fits up there; status and period read as the receipt's first line. -->
		<header class="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 pt-4">
			<Badge
				:theme="invoiceTheme(detail.data.status)"
				variant="subtle"
				:label="detail.data.status"
			/>
			<span class="text-p-sm text-ink-gray-5">
				{{ detail.data.invoice_type }}
				·
				{{ billingPeriod(detail.data.period_start, detail.data.period_end) }}
				<span v-if="detail.data.due_date">
					· Due {{ shortDate(detail.data.due_date) }}</span
				>
			</span>
		</header>

		<InvoiceReceipt :invoice="detail.data" :overdue="isOverdue" />

		<!-- The panel pins this in a footer; a page has no footer to pin to, so the
		     one state-dependent action closes the receipt out. Settling an invoice
		     is the helpful way out of an overdue state, not a destructive act —
		     the default solid, not red. -->
		<div v-if="canPay || settling" class="px-4 pt-4">
			<Button
				v-if="canPay"
				variant="solid"
				class="w-full"
				icon-left="lucide-credit-card"
				:label="`Pay ${money(detail.data.expected_collection, detail.data.currency)} now`"
				:loading="payBusy"
				@click="pay()"
			/>
			<div
				v-else
				class="flex items-center justify-center gap-2 py-1 text-p-sm text-ink-gray-6"
			>
				<Spinner size="md" />
				<span>Waiting for your bank to confirm the payment…</span>
			</div>
		</div>
	</div>
</template>
