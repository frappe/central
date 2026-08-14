<script setup lang="ts">
import {
	Badge,
	Breadcrumbs,
	Button,
	LoadingText,
	PageHeader,
	PageHeaderMobile,
	Spinner,
} from 'frappe-ui'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import InvoiceListView from '@/components/billing/InvoiceListView.vue'
import InvoiceReceipt from '@/components/billing/InvoiceReceipt.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import NavDrawerTitle from '@/components/navigation/NavDrawerTitle.vue'
import { invoicePath, useInvoiceDetail } from '@/composables/useInvoiceDetail'
import { useInvoices } from '@/composables/useInvoices'
import { useIsMobile } from '@/composables/useIsMobile'
import { useSession } from '@/composables/useSession'
import { billingPeriod, shortDate } from '@/lib/date'
import { money } from '@/lib/format'
import { invoiceTheme } from '@/lib/status'
import type { InvoiceSummary } from '@/types/billing'

// Billing › Invoices (#70) — list (left) + docked 24rem receipt panel (right)
// that slides in, mirroring the FC V2 prototype's invoice anatomy. Invoices come
// from the team-scoped list_invoices/get_invoice endpoints (curated fields, not
// raw reportview), so we filter client-side over that list.
// A phone gets the list alone: there's no room to dock 24rem beside it, so a row
// pushes /billing/invoices/:name instead and the receipt is a page of its own.
const route = useRoute()
const router = useRouter()
const isMobile = useIsMobile()
const {
	invoices,
	loading: invoicesLoading,
	reload: reloadInvoices,
} = useInvoices()

// ── Detail panel ──
const selected = ref<InvoiceSummary | null>(null)

// Holds the invoice while the panel slides out, so the receipt doesn't blank
// mid-animation. `detail` keeps its data, so the body follows suit.
const shown = ref<InvoiceSummary | null>(null)
watch(selected, (invoice) => {
	if (invoice) shown.value = invoice
})

const { detail, isOverdue, settling, canPay, payBusy, pay } = useInvoiceDetail(
	() => selected.value?.name ?? null,
	{ onPaid: reloadInvoices },
)

// A row means "show me this invoice" — which is the panel here and a page on a
// phone, where the panel doesn't render at all.
function selectRow(inv: InvoiceSummary): void {
	if (isMobile.value) router.push(invoicePath(inv.name))
	else selected.value = inv
}

// Open the latest invoice expanded on first load — list_invoices is ordered newest
// first, so that's row 0. A `?invoice=` deep link (from global search) selects
// that row instead. Only auto-select once: after the user closes the panel (or a
// refetch arrives), we leave their choice alone.
let autoSelected = false
watch(
	() => invoices.value,
	(rows) => {
		if (autoSelected || selected.value || !rows.length) return
		const wanted = String(route.query.invoice ?? '')
		const asked = wanted ? rows.find((r) => r.name === wanted) : undefined
		// Nothing auto-opens on mobile: opening a receipt there is a navigation, and
		// landing on the list only to be carried off it is not what tapping Invoices
		// asked for. A deep link did ask for one invoice by name, so that still goes
		// through — straight to its page, replacing so Back returns to the list.
		if (isMobile.value) {
			// Latch either way. Only the first list this page sees may carry you
			// off it: leaving it unlatched means a later refetch — a payment, a
			// team switch — can act on a `?invoice=` still sitting in the URL and
			// yank you off a list you've been reading for minutes.
			autoSelected = true
			if (asked) router.replace(invoicePath(asked.name))
			return
		}
		autoSelected = true
		selectRow(asked ?? rows[0])
	},
	{ immediate: true },
)

// A team switch invalidates the open receipt — the list refetches on its own
// (reactive teamParams), but the panel would keep showing the old team's
// invoice. Close it and let the new team's latest auto-select.
const { activeTeam } = useSession()
watch(activeTeam, (team, previous) => {
	if (!previous || team === previous) return
	selected.value = null
	shown.value = null
	autoSelected = false
})
</script>

<template>
	<PageHeaderMobile class="sm:hidden">
		<NavDrawerTitle title="Invoices" />
	</PageHeaderMobile>

	<!-- 'Billing' is the sidebar group Invoices sits in, not a page above it —
	     Overview is its sibling. So it labels the trail without linking. -->
	<PageHeader class="hidden sm:flex">
		<Breadcrumbs
			:items="[
				{ label: 'Billing' },
				{ label: 'Invoices', route: { name: 'BillingInvoices' } },
			]"
		/>
	</PageHeader>

	<!-- The list/receipt row is desktop-only scaffolding: DesktopShell doesn't
	     scroll, so the panes own their overflow there. On mobile MobileShell is
	     the scroller and the page has to fall through to it, or the bottom nav
	     eats the last rows. -->
	<div class="sm:flex sm:h-full sm:min-h-0">
		<!-- LIST — capped and centered so rows stay scannable when the panel is
         closed; the cap matches the Limit tiers page. -->
		<div class="sm:min-w-0 sm:flex-1 sm:overflow-y-auto">
			<div class="mx-auto w-full max-w-3xl px-4 py-5 sm:px-6">
				<InvoiceListView
					:invoices="invoices"
					:loading="invoicesLoading && !invoices.length"
					:active-name="selected?.name"
					@row-click="selectRow"
				/>
			</div>
		</div>

		<!-- Docked receipt panel — the shared SidePanel, slides in beside the
         list, never over it. Header carries all invoice identity: number +
         status together, so the body never needs a labelled "Status" row.
         Desktop only: at 24rem it can't sit beside anything on a phone, and
         stacked under the list it's just an overflowing second screen.
         GROUNDING GAP (#70): no email-invoice / download-PDF endpoints yet,
         so both header actions stay disabled until the backend lands them. -->
		<SidePanel
			v-if="!isMobile"
			:open="!!selected"
			@update:open="(v: boolean) => !v && (selected = null)"
		>
			<template #title>
				<div v-if="shown" class="flex items-center gap-2">
					<span class="truncate text-base-semibold text-ink-gray-9">
						{{ shown.name }}
					</span>
					<Badge
						:theme="invoiceTheme(shown.status)"
						variant="subtle"
						:label="shown.status"
					/>
				</div>
			</template>
			<template #subtitle>
				<div v-if="shown" class="truncate text-p-sm text-ink-gray-5">
					{{ shown.invoice_type }}
					·
					{{ billingPeriod(shown.period_start, shown.period_end) }}
					<span v-if="shown.due_date">
						· Due {{ shortDate(shown.due_date) }}</span
					>
				</div>
			</template>
			<template #actions>
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

			<div v-if="detail.loading && !detail.data" class="space-y-3 p-4">
				<LoadingText :lines="6" />
			</div>

			<InvoiceReceipt
				v-else-if="detail.data"
				:invoice="detail.data"
				:overdue="isOverdue"
			/>

			<!-- The footer carries only the one state-dependent action. Settling an
           invoice is the helpful way out of an overdue state, not a
           destructive act — the default solid, not red. -->
			<template v-if="detail.data && (canPay || settling)" #footer>
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
			</template>
		</SidePanel>
	</div>
</template>
