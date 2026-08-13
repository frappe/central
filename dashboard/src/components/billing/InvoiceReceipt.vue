<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ChargeBreakdown from '@/components/billing/ChargeBreakdown.vue'
import { shortDate } from '@/lib/date'
import { money } from '@/lib/format'
import type { InvoiceDetail } from '@/types/billing'

// The receipt itself and nothing around it: what the invoice is made of, what it
// comes to, and what has happened to it. Both hosts supply their own chrome —
// the docked panel puts identity in its header and Pay in its footer, the mobile
// page puts them above and below this — so neither lives here.
const props = defineProps<{
	invoice: InvoiceDetail
	/** Owned by useInvoiceDetail, which holds the status rules. */
	overdue?: boolean
}>()

// Activity is folded away by default — for a settled invoice the log is
// reference, not news. Fold it again when switching invoices.
const activityExpanded = ref(false)
watch(
	() => props.invoice.name,
	() => (activityExpanded.value = false),
)

// Timeline dot colour per event theme; gray for informational events, so color
// stays reserved for outcomes.
const DOTS: Record<string, string> = {
	green: 'bg-[var(--ink-green-6)]',
	red: 'bg-[var(--ink-red-6)]',
}
const dotClass = (theme: string): string =>
	DOTS[theme] || 'bg-[var(--ink-gray-4)]'

const paidWithIcon = computed(() =>
	/upi/i.test(props.invoice.paid_with?.method_type ?? '')
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
	if (ev.amount) parts.push(money(ev.amount, ev.currency || props.invoice.currency))
	if (ev.detail) parts.push(ev.detail)
	return parts.join(' · ')
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col">
		<p
			v-if="overdue"
			class="flex items-center gap-1.5 px-4 pt-4 text-p-sm text-ink-red-7"
		>
			<span class="lucide-triangle-alert size-3.5 shrink-0" />
			Due {{ shortDate(invoice.due_date) }} — overdue
		</p>

		<!-- Receipt: plan charges per server, then metered add-ons — each
         section a plain eyebrow with its subtotal, like the V2 receipt. -->
		<!-- No inner scroll: the panel already scrolls, and a second scroller
		     here clipped the receipt mid-row once a team had more than one
		     machine on the invoice. -->
		<div class="shrink-0 px-4 pt-4">
			<ChargeBreakdown :lines="invoice.items" :currency="invoice.currency" />
		</div>

		<!-- Cost breakdown + Activity -->
		<div class="mt-4 border-t border-outline-gray-2 px-4">
			<dl class="space-y-2 py-3 text-sm">
				<div class="flex justify-between gap-3">
					<dt class="text-ink-gray-5">Subtotal</dt>
					<dd class="tabular-nums text-ink-gray-8">
						{{ money(invoice.subtotal, invoice.currency) }}
					</dd>
				</div>
				<div v-if="invoice.output_tax_amount" class="flex justify-between gap-3">
					<dt class="text-ink-gray-5">
						{{ invoice.output_tax_type || 'Tax' }}
						<template v-if="invoice.output_tax_rate">
							({{ invoice.output_tax_rate }}%)</template
						>
					</dt>
					<dd class="tabular-nums text-ink-gray-8">
						{{ money(invoice.output_tax_amount, invoice.currency) }}
					</dd>
				</div>
				<p v-if="invoice.zero_rating_reason" class="text-p-sm text-ink-gray-5">
					{{ invoice.zero_rating_reason }}
				</p>
				<div v-if="invoice.credit_applied" class="flex justify-between gap-3">
					<dt class="text-ink-green-5">Credits applied</dt>
					<dd class="tabular-nums text-ink-green-5">
						−{{ money(invoice.credit_applied, invoice.currency) }}
					</dd>
				</div>
				<div
					class="mt-1 flex justify-between gap-3 border-t border-outline-gray-1 pt-2.5 font-semibold"
				>
					<dt class="text-ink-gray-8">Total</dt>
					<dd class="tabular-nums text-ink-gray-9">
						{{ money(invoice.total, invoice.currency) }}
					</dd>
				</div>
				<!-- Which method settled it — a quiet receipt line, not a form
             row. Falls back to the paid amount when the method is gone. -->
				<div
					v-if="invoice.paid_with"
					class="flex justify-between gap-3 text-p-sm text-ink-gray-5"
				>
					<dt>Paid with</dt>
					<dd class="flex min-w-0 items-center gap-1.5">
						<span
							class="size-3.5 shrink-0 text-ink-gray-4"
							:class="paidWithIcon"
							aria-hidden="true"
						/>
						<span class="truncate">{{ invoice.paid_with.label }}</span>
					</dd>
				</div>
				<div
					v-else-if="invoice.amount_paid"
					class="flex justify-between gap-3 text-p-sm text-ink-gray-5"
				>
					<dt>Paid</dt>
					<dd class="tabular-nums">
						{{ money(invoice.amount_paid, invoice.currency) }}
					</dd>
				</div>
			</dl>

			<!-- Activity — this invoice's own history. Folded away entirely:
           for a settled invoice the log is reference, not news. -->
			<section
				v-if="invoice.activity?.length"
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
						{{ invoice.activity.length }}
					</span>
				</button>
				<ol v-if="activityExpanded" class="relative mt-3">
					<li
						v-for="(ev, idx) in invoice.activity"
						:key="idx"
						class="relative flex gap-3 pb-4 last:pb-0"
					>
						<!-- Rail: one continuous line running through the column, with
                 the solid dot sitting on top of it. The line is dropped on
                 the last row so it doesn't dangle. -->
						<div class="relative flex w-2.5 shrink-0 justify-center">
							<span
								v-if="idx < invoice.activity.length - 1"
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
								<span class="shrink-0 tabular-nums text-p-sm text-ink-gray-5">
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
</template>
