<script setup lang="ts">
import { Badge, Button, LoadingText, Spinner, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { API, method } from '@/api/methods'
import InvoiceListView from '@/components/billing/InvoiceListView.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useInvoices } from '@/composables/useInvoices'
import { usePayInvoice } from '@/composables/usePayInvoice'
import { usePayInvoiceCheckout } from '@/composables/usePayInvoiceCheckout'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { billingPeriod, shortDate } from '@/lib/date'
import { money } from '@/lib/format'
import { invoiceTheme } from '@/lib/status'
import type {
	BillingLine,
	CollectionStatus,
	InvoiceDetail,
	InvoiceSummary,
} from '@/types/billing'

// Billing › Invoices (#70) — list (left) + docked 24rem receipt panel (right)
// that slides in, mirroring the FC V2 prototype's invoice anatomy. Invoices come
// from the team-scoped list_invoices/get_invoice endpoints (curated fields, not
// raw reportview), so we filter client-side over that list.
const route = useRoute()
const { canManageBilling } = useCapabilities()
const {
	invoices,
	loading: invoicesLoading,
	reload: reloadInvoices,
} = useInvoices()

const collection = useCall<CollectionStatus, { team: string }>({
	url: method(API.collectionStatus),
	params: teamParams,
	immediate: false,
	refetch: true,
})
whenTeamReady(() => collection.reload())

// ── Detail panel ──
const selected = ref<InvoiceSummary | null>(null)
const detail = useCall<InvoiceDetail, { name: string }>({
	url: method(API.invoice),
	immediate: false,
})

// Activity is folded away by default — for a settled invoice the log is
// reference, not news. Fold it again when switching invoices.
const activityExpanded = ref(false)

// Holds the invoice while the panel slides out, so the receipt doesn't blank
// mid-animation. `detail` keeps its data, so the body follows suit.
const shown = ref<InvoiceSummary | null>(null)
watch(selected, (invoice) => {
	if (invoice) shown.value = invoice
})

async function selectRow(inv: InvoiceSummary): Promise<void> {
	selected.value = inv
	activityExpanded.value = false
	await detail.submit({ name: inv.name })
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
		autoSelected = true
		const wanted = route.query.invoice
		const row = (wanted && rows.find((r) => r.name === wanted)) || rows[0]
		selectRow(row)
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

// Open OR Overdue is still collectable — an overdue invoice is the one the customer
// most needs to settle (dunning failed on the card), so it must offer Pay too.
const isPayable = computed(() =>
	['open', 'overdue'].includes(String(detail.data?.status).toLowerCase()),
)
// The panel's one pre-items line, and only in the problem state — its single
// use of color above the fold.
const isOverdue = computed(
	() =>
		String(detail.data?.status).toLowerCase() === 'overdue' &&
		!!detail.data?.due_date,
)
// A charge already in flight (or captured, awaiting the settlement webhook) means
// the money is moving — show a "settling" status, never a second Pay button.
const settling = computed(
	() => isPayable.value && !!detail.data?.payment_in_progress,
)
// Only offer Pay when something is actually collectable — a zero-due invoice
// (e.g. a trial Cost Report) must never render a "Pay 0.00" button.
const hasDue = computed(() => Number(detail.data?.expected_collection) > 0)
const canPay = computed(
	() =>
		canManageBilling.value &&
		isPayable.value &&
		!settling.value &&
		hasDue.value,
)

function refresh(): void {
	reloadInvoices()
	if (selected.value) detail.submit({ name: selected.value.name })
}
const { run: payInvoice, loading: paying } = usePayInvoice({ onDone: refresh })
const { run: payCheckout, loading: payingCheckout } = usePayInvoiceCheckout({
	onDone: refresh,
})

// manual_checkout teams settle on-session (any amount, no ₹15k limit); everyone
// else uses the off-session charge against their saved method.
const manualMode = computed(
	() => collection.data?.collection_mode === 'Manual Checkout',
)
const payBusy = computed(() => paying.value || payingCheckout.value)
function pay(name: string): Promise<unknown> {
	return manualMode.value ? payCheckout(name) : payInvoice(name)
}

// Timeline dot colour per event theme; gray for informational events, so color
// stays reserved for outcomes.
const DOTS: Record<string, string> = {
	green: 'bg-[var(--ink-green-7)]',
	red: 'bg-[var(--ink-red-7)]',
}
const dotClass = (theme: string): string =>
	DOTS[theme] || 'bg-[var(--ink-gray-4)]'

// Receipt sections — plan lines are the per-server bundles; everything else
// (metered overage, à-la-carte components) reads as an add-on.
const servers = computed(() =>
	(detail.data?.items ?? []).filter((li) => li.kind === 'Plan'),
)
const addons = computed(() =>
	(detail.data?.items ?? []).filter((li) => li.kind !== 'Plan'),
)
const sum = (rows: BillingLine[]): number =>
	rows.reduce((t, li) => t + Number(li.amount || 0), 0)

const paidWithIcon = computed(() =>
	/upi/i.test(detail.data?.paid_with?.method_type ?? '')
		? 'lucide-smartphone'
		: 'lucide-credit-card',
)

// "31 May 2026, 09:00" → "31 May 2026": the date carries the story; the
// clock time is noise at timeline granularity.
const eventDate = (at: string | null): string => String(at ?? '').split(',')[0]

// One gray sentence under the label: amount first, then the backend's detail.
const eventDetail = (ev: {
	detail: string | null
	amount: number
	currency?: string
}): string => {
	const parts: string[] = []
	if (ev.amount)
		parts.push(money(ev.amount, ev.currency || detail.data?.currency))
	if (ev.detail) parts.push(ev.detail)
	return parts.join(' · ')
}
</script>

<template>
	<div class="flex h-full min-h-0">
		<!-- LIST — capped and centered so rows stay scannable when the panel is
         closed; the cap matches the Limit tiers page. -->
		<div class="min-w-0 flex-1 overflow-y-auto">
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
         GROUNDING GAP (#70): no email-invoice / download-PDF endpoints yet,
         so both header actions stay disabled until the backend lands them. -->
		<SidePanel
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

			<!-- Body: the receipt list scrolls on its own; the cost breakdown and
           Activity sit below it, so the totals never shift as the list
           scrolls. Activity opens below and is revealed by scrolling. -->
			<div v-else-if="detail.data" class="flex min-h-0 flex-1 flex-col">
					<p
						v-if="isOverdue"
						class="flex items-center gap-1.5 px-4 pt-4 text-p-sm text-ink-red-8"
					>
						<span class="lucide-triangle-alert size-3.5 shrink-0" />
						Due {{ shortDate(detail.data.due_date) }} — overdue
					</p>

					<!-- Receipt: plan charges per server, then metered add-ons — each
               section a plain eyebrow with its subtotal, like the V2 receipt. -->
					<div class="max-h-80 shrink-0 space-y-4 overflow-y-auto px-4 pt-4">
						<section v-if="servers.length">
							<div class="mb-1 flex items-center justify-between gap-3">
								<span
									class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5"
								>
									Servers
								</span>
								<span class="text-p-sm tabular-nums text-ink-gray-5">
									{{ money(sum(servers), detail.data.currency) }}
								</span>
							</div>
							<ul>
								<li
									v-for="(li, idx) in servers"
									:key="idx"
									class="flex items-center justify-between gap-3 py-1.5"
								>
									<div class="min-w-0">
										<p class="truncate text-sm text-ink-gray-8">{{ li.item }}</p>
										<!-- The rate belongs on the line. A mid-month resize splits one
										     server into several segments, and without the rate they read as
										     the same charge repeated — the price is the only thing that
										     actually differs between them. -->
										<p
											v-if="li.detail || li.rate"
											class="truncate text-p-sm text-ink-gray-5"
										>
											{{ li.detail }}
											<template v-if="li.rate">
												· {{ money(li.rate, detail.data.currency) }}/mo</template
											>
										</p>
									</div>
									<span
										class="shrink-0 pl-3 text-sm tabular-nums text-ink-gray-8"
									>
										{{ money(li.amount, detail.data.currency) }}
									</span>
								</li>
							</ul>
						</section>

						<section v-if="addons.length">
							<div class="mb-1 flex items-center justify-between gap-3">
								<span
									class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5"
								>
									Services
								</span>
								<span class="text-p-sm tabular-nums text-ink-gray-5">
									{{ money(sum(addons), detail.data.currency) }}
								</span>
							</div>
							<ul>
								<li
									v-for="(li, idx) in addons"
									:key="idx"
									class="flex items-center justify-between gap-3 py-1.5"
								>
									<div class="min-w-0">
										<p class="truncate text-sm text-ink-gray-8">{{ li.item }}</p>
										<p v-if="li.detail" class="truncate text-p-sm text-ink-gray-5">
											{{ li.detail }}
										</p>
									</div>
									<span
										class="shrink-0 pl-3 text-sm tabular-nums text-ink-gray-8"
									>
										{{ money(li.amount, detail.data.currency) }}
									</span>
								</li>
							</ul>
						</section>
					</div>

					<!-- Cost breakdown + Activity -->
					<div class="mt-4 border-t border-outline-gray-2 px-4">
						<dl class="space-y-2 py-3 text-sm">
							<div class="flex justify-between gap-3">
								<dt class="text-ink-gray-5">Subtotal</dt>
								<dd class="tabular-nums text-ink-gray-8">
									{{ money(detail.data.subtotal, detail.data.currency) }}
								</dd>
							</div>
							<div
								v-if="detail.data.output_tax_amount"
								class="flex justify-between gap-3"
							>
								<dt class="text-ink-gray-5">
									{{ detail.data.output_tax_type || 'Tax' }}
									<template v-if="detail.data.output_tax_rate">
										({{ detail.data.output_tax_rate }}%)</template
									>
								</dt>
								<dd class="tabular-nums text-ink-gray-8">
									{{ money(detail.data.output_tax_amount, detail.data.currency) }}
								</dd>
							</div>
							<p
								v-if="detail.data.zero_rating_reason"
								class="text-p-sm text-ink-gray-5"
							>
								{{ detail.data.zero_rating_reason }}
							</p>
							<div
								v-if="detail.data.credit_applied"
								class="flex justify-between gap-3"
							>
								<dt class="text-ink-green-6">Credits applied</dt>
								<dd class="tabular-nums text-ink-green-6">
									−{{ money(detail.data.credit_applied, detail.data.currency) }}
								</dd>
							</div>
							<div
								class="mt-1 flex justify-between gap-3 border-t border-outline-gray-1 pt-2.5 font-semibold"
							>
								<dt class="text-ink-gray-8">Total</dt>
								<dd class="tabular-nums text-ink-gray-9">
									{{ money(detail.data.total, detail.data.currency) }}
								</dd>
							</div>
							<!-- Which method settled it — a quiet receipt line, not a form
                   row. Falls back to the paid amount when the method is gone. -->
							<div
								v-if="detail.data.paid_with"
								class="flex justify-between gap-3 text-p-sm text-ink-gray-5"
							>
								<dt>Paid with</dt>
								<dd class="flex min-w-0 items-center gap-1.5">
									<span
										class="size-3.5 shrink-0 text-ink-gray-4"
										:class="paidWithIcon"
										aria-hidden="true"
									/>
									<span class="truncate">{{ detail.data.paid_with.label }}</span>
								</dd>
							</div>
							<div
								v-else-if="detail.data.amount_paid"
								class="flex justify-between gap-3 text-p-sm text-ink-gray-5"
							>
								<dt>Paid</dt>
								<dd class="tabular-nums">
									{{ money(detail.data.amount_paid, detail.data.currency) }}
								</dd>
							</div>
						</dl>

						<!-- Activity — this invoice's own history. Folded away entirely:
                 for a settled invoice the log is reference, not news. -->
						<section
							v-if="detail.data.activity?.length"
							class="border-t border-outline-gray-1 py-3"
						>
							<button
								class="flex w-full items-center gap-1.5 text-left"
								:aria-expanded="activityExpanded"
								@click="activityExpanded = !activityExpanded"
							>
								<span
									class="lucide-chevron-right size-3.5 shrink-0 text-ink-gray-5 transition-transform duration-150 ease-out"
									:class="activityExpanded ? 'rotate-90' : ''"
								/>
								<h3 class="text-sm-medium text-ink-gray-8">Activity</h3>
								<span class="text-p-sm text-ink-gray-5">
									{{ detail.data.activity.length }}
								</span>
							</button>
							<ol v-if="activityExpanded" class="relative mt-3">
								<li
									v-for="(ev, idx) in detail.data.activity"
									:key="idx"
									class="relative flex gap-3 pb-4 last:pb-0"
								>
									<!-- Rail: one continuous line running through the column, with
                       the solid dot sitting on top of it. The line is dropped on
                       the last row so it doesn't dangle. -->
									<div class="relative flex w-2.5 shrink-0 justify-center">
										<span
											v-if="idx < detail.data.activity.length - 1"
											class="absolute left-1/2 top-2 h-[calc(100%+1rem)] w-px -translate-x-1/2 bg-[var(--outline-gray-2)]"
										/>
										<span
											class="relative z-10 mt-1 size-2 shrink-0 rounded-full"
											:class="dotClass(ev.theme)"
										/>
									</div>
									<div class="min-w-0 flex-1">
										<div class="flex items-baseline justify-between gap-2">
											<span class="text-sm-medium text-ink-gray-8">
												{{ ev.title }}
											</span>
											<span
												class="shrink-0 tabular-nums text-p-sm text-ink-gray-5"
											>
												{{ eventDate(ev.at) }}
											</span>
										</div>
										<p
											v-if="eventDetail(ev)"
											class="mt-0.5 break-words text-p-sm text-ink-gray-5"
										>
											{{ eventDetail(ev) }}
										</p>
									</div>
								</li>
							</ol>
						</section>
					</div>
				</div>

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
					@click="pay(detail.data.name)"
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
