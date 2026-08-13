<script setup lang="ts">
import {
	Breadcrumbs,
	Button,
	LoadingText,
	PageHeader,
	PageHeaderMobile,
	useCall,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import NavDrawerTitle from '@/components/navigation/NavDrawerTitle.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import type { TierLevel, TrustTier } from '@/types/billing'

// Layout mirrors the frappe-cloud-v2 prototype: a standing band, a tiers table
// whose Requirements column shows each rung's promotion gates against the team's
// live progress, and a "how it works" explainer.
const { activeTeam } = useSession()
const { forecast, credit, methods } = useBillingOverview()

const tier = useCall<TrustTier, { team: string }>({
	url: method(API.trustTier),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => tier.reload())

// The empty state's button is the real action, not a pointer to Billing:
// billing details first when the profile is incomplete, then the add-method
// flow — both dialogs mounted on this page.
const { complete, setupDialogOpen } = useBillingSetup()
const showAddMethod = ref(false)

function startFirstTier(): void {
	// requireSetup()'s toast explains a detour — pointless here, where the
	// button already says "Add billing details" when the profile is incomplete.
	if (!complete.value) {
		setupDialogOpen.value = true
		return
	}
	showAddMethod.value = true
}

function onMethodAdded(): void {
	tier.reload()
	methods.reload()
}

const currency = computed(() => tier.data?.currency || 'INR')
const cur = computed(() => tier.data?.current)
const prog = computed(() => tier.data?.progress)
const monthlySpend = computed(() => forecast.data?.projected_total)

// Whole months since the team's first paid invoice, for the "Customer for" stat.
const payingSince = computed(() => {
	const firstPaidAt = prog.value?.first_paid_at

	if (!firstPaidAt) return null

	const months = Math.max(
		0,
		Math.floor(
			(Date.now() - new Date(firstPaidAt).getTime()) /
				(1000 * 60 * 60 * 24 * 30),
		),
	)

	return months < 1 ? '< 1 month' : `${months} month${months === 1 ? '' : 's'}`
})

// This cycle's spend drawn against the current cap, so the limit is the
// endpoint of a bar rather than a number floating elsewhere on the page.
const cycleRatio = computed(() => {
	const cap = Number(cur.value?.max_spend ?? 0)
	const spent = Number(monthlySpend.value ?? 0)
	return cap ? Math.min(1, spent / cap) : 0
})

// Same treatment for the resource cap: a live count against the ceiling,
// in the same row grammar as the cycle meter.
const resourcesUsed = computed(() => Number(prog.value?.resources_used ?? 0))
const resourceRatio = computed(() => {
	const cap = Number(cur.value?.max_resource_count ?? 0)
	return cap ? Math.min(1, resourcesUsed.value / cap) : 0
})

// Quiet account record for the card footer — context, not a call to action.
// Only records that exist: a team that has never paid an invoice gets no
// "Last paid invoice ₹0" line, and with nothing to show the footer hides.
const record = computed(() =>
	[
		payingSince.value ? `Customer for ${payingSince.value}` : null,
		Number(prog.value?.last_paid_invoice_amount) > 0
			? `Last paid invoice ${money(prog.value!.last_paid_invoice_amount, currency.value, { trimTrailingZeros: true })}`
			: null,
	]
		.filter(Boolean)
		.join(' · '),
)

// Reference, not news — folded away until you're asking why you're on this rung.
const howOpen = ref(false)

const nextLevel = computed(() => tier.data?.next ?? null)

// The one question this page exists to answer: how far to the next rung. Gates
// are shown as distance travelled, not as a yes/no — a bar plus the two numbers
// behind it, since those numbers are load-bearing and appear nowhere else.
interface Gate {
	label: string
	done: boolean
	ratio: number
	detail: string
}

const gates = computed<Gate[]>(() => {
	const level = nextLevel.value
	const p = prog.value
	if (!level || !p) return []

	const out: Gate[] = []
	const gate = (
		label: string,
		have: number,
		need: number,
		fmt: (v: number) => string = String,
	) => {
		const done = have >= need
		out.push({
			label,
			done,
			ratio: Math.min(1, need ? have / need : 1),
			// Clamped so a met gate reads "3 of 3" rather than "9 of 3".
			detail: `${fmt(done ? need : have)} of ${fmt(need)}`,
		})
	}

	if (level.min_paid_invoices) {
		gate('Paid invoices', Number(p.paid_invoices ?? 0), level.min_paid_invoices)
	}
	if (level.min_cumulative_paid) {
		gate(
			'Paid to date',
			Number(p.cumulative_paid ?? 0),
			Number(level.min_cumulative_paid),
			(v) => money(Number(v), currency.value),
		)
	}
	return out
})

// The rail is a route, not a form: travelled rungs are filled stops, the
// current rung is the largest solid mark, rungs ahead shrink to plain nodes.
// No rings or hollows — a ringed circle beside a table reads as a radio button.
const DOT_CLASSES: Record<RungState, string> = {
	reached: 'size-2.5 bg-surface-gray-6',
	current: 'size-3 bg-surface-gray-9',
	locked: 'size-1.5 bg-surface-gray-4',
}

const tierLabel = (level: TierLevel | null | undefined): string => {
	if (!level) return '—'
	return level.tier || '—'
}

interface Requirement {
	text: string
	met: boolean
}

// A rung's promotion gates, checked against the team's live progress. The base
// rung's gate is a payment method or prepaid credits — everything past it is
// paid-invoice tenure + cumulative spend.
const requirementsFor = (level: TierLevel): Requirement[] => {
	const p = prog.value
	const paid = Number(p?.paid_invoices ?? 0)
	const cumulative = Number(p?.cumulative_paid ?? 0)

	if (level.sequence <= 0) {
		const hasChargeableMethod = (methods.data ?? []).some(
			(m) => m.status === 'Active' && !m.reauth_required,
		)
		const met = hasChargeableMethod || Number(credit.data?.balance ?? 0) > 0
		return [{ text: 'Payment method added or prepaid credits available', met }]
	}

	const reqs: Requirement[] = []

	if (level.min_paid_invoices) {
		const n = level.min_paid_invoices

		reqs.push({
			text: `≥ ${n} paid invoice${n === 1 ? '' : 's'}`,
			met: paid >= n,
		})
	}

	if (level.min_cumulative_paid) {
		reqs.push({
			text: `≥ ${money(level.min_cumulative_paid, currency.value)} paid to date`,
			met: cumulative >= Number(level.min_cumulative_paid),
		})
	}

	return reqs.length
		? reqs
		: [{ text: 'No additional requirements', met: true }]
}

type RungState = 'reached' | 'current' | 'locked'

// Every rung, tagged reached / current / locked relative to where the team is.
const levels = computed(() => {
	const all = (tier.data?.all_levels ?? []).filter((l): l is TierLevel => !!l)
	const ci = all.findIndex((l) => l.tier === cur.value?.tier)
	return all.map((l, i) => ({
		...l,
		state: (i < ci ? 'reached' : i === ci ? 'current' : 'locked') as RungState,
	}))
})
</script>

<template>
	<PageHeaderMobile class="sm:hidden">
		<NavDrawerTitle title="Limit tiers" />
	</PageHeaderMobile>

	<!-- 'Billing' is the sidebar group these three pages sit in, not a page above
	     them — Overview is their sibling. So it labels the trail without linking. -->
	<PageHeader class="hidden sm:flex">
		<Breadcrumbs
			:items="[
				{ label: 'Billing' },
				{ label: 'Limit tiers', route: { name: 'SpendingLimits' } },
			]"
		/>
	</PageHeader>

	<!-- Desktop-only scroll box: DesktopShell doesn't scroll, so the page owns its
	     overflow there. On mobile MobileShell is the scroller and this has to get
	     out of the way, or the bottom nav eats the last rows. -->
	<div class="sm:h-full sm:overflow-y-auto">
		<div
			class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:gap-8 sm:px-6 sm:py-8"
		>
			<LoadingText v-if="tier.loading && !tier.data" :lines="6" />

			<template v-else-if="levels.length">
				<!-- "Current:" mirrors "Next:" below — parallel zones, labels outside
				     the boxes. Current is reference, so its values sit one size below
				     the gate values: the page's real news is the unmet gate. -->
				<section v-if="cur">
					<p class="text-p-md text-ink-gray-7 sm:text-p-base">
						Current:
						<span class="font-medium text-ink-gray-9">
							{{ tierLabel(cur) }} tier
						</span>
					</p>

					<div
						class="mt-3 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
					>
						<div class="grid gap-4 sm:grid-cols-2">
							<div>
								<p class="text-p-sm text-ink-gray-5">This cycle</p>
								<p
									class="mt-1 text-base-semibold tabular-nums"
									:class="
										cycleRatio >= 0.8 ? 'text-ink-amber-6' : 'text-ink-gray-9'
									"
								>
									{{ money(monthlySpend, currency) }} of
									{{ money(cur.max_spend, currency) }}
								</p>
							</div>

							<div v-if="cur.max_resource_count != null">
								<p class="text-p-sm text-ink-gray-5">Resources</p>
								<p
									class="mt-1 text-base-semibold tabular-nums"
									:class="
										resourceRatio >= 0.8
											? 'text-ink-amber-6'
											: 'text-ink-gray-9'
									"
								>
									{{ resourcesUsed }} of {{ cur.max_resource_count }}
								</p>
							</div>
						</div>

						<p v-if="!nextLevel" class="mt-4 text-p-base text-ink-gray-5">
							This is the highest tier
						</p>

						<p v-if="record" class="mt-4 text-p-sm text-ink-gray-5">
							{{ record }}
						</p>
					</div>
				</section>

				<!-- A team with no tier yet gets the pitch and the actual action, not
				     a pointer to another page: the first rung's concrete numbers, the
				     fear named and defused, and the next step as a button. -->
				<section
					v-else
					class="rounded-6 border border-outline-gray-2 bg-surface-base p-5"
				>
					<!-- The headline is the thing the tier lets you DO, not the tier —
				     and a team already gets its first server without one, so the
				     pitch is growing past it. -->
					<h2 class="text-xl-semibold text-ink-gray-9">
						Grow beyond your first server
					</h2>
					<!-- No figures here: the Beginner row directly below carries them. -->
					<p class="mt-1.5 text-p-base text-ink-gray-6">
						Add a payment method to start on the
						{{ tierLabel(levels[0]) }} tier. You only pay for what you use,
						and your limit rises as your payment history grows.
					</p>
					<Button
						class="mt-4"
						variant="solid"
						:label="complete ? 'Add payment method' : 'Add billing details'"
						@click="startFirstTier"
					/>
				</section>

				<!-- The distance to the next rung, out in the open. The gates are
				     independent AND-conditions, so they sit side by side as peers —
				     a cleared one is a check, an open one is a distance. -->
				<section v-if="nextLevel">
					<p class="text-p-base text-ink-gray-7">
						Next:
						<span class="font-medium text-ink-gray-9">
							{{ tierLabel(nextLevel) }} tier
						</span>
					</p>

					<!-- One bordered container, gates as joined halves: an AND reads as
					     one card with a shared wall, not two independent choices. -->
					<div
						class="mt-3 rounded-6 border border-outline-gray-2 bg-surface-base"
						:class="
							gates.length > 1
								? 'grid divide-y divide-outline-gray-2 sm:grid-cols-2 sm:divide-x sm:divide-y-0'
								: ''
						"
					>
						<div v-for="gate in gates" :key="gate.label" class="p-4">
							<p class="text-p-sm text-ink-gray-5">{{ gate.label }}</p>
							<p
								class="mt-1 flex items-center gap-1.5 text-lg-semibold tabular-nums text-ink-gray-9"
							>
								<span
									v-if="gate.done"
									class="lucide-check size-4 shrink-0 text-ink-green-5"
									aria-hidden="true"
								/>
								{{ gate.detail }}
							</p>
							<!-- Both tiles keep the bar so they share one anatomy; a done
							     gate fills it in the muted "settled" tone the rail uses,
							     the open gate keeps the dark outstanding fill. -->
							<span
								class="mt-3 block h-1 overflow-hidden rounded-full bg-surface-gray-3"
							>
								<span
									class="block h-full rounded-full transition-[width] duration-300"
									:class="gate.done ? 'bg-surface-gray-5' : 'bg-surface-gray-9'"
									:style="{
										width: `${gate.done ? 100 : Math.round(gate.ratio * 100)}%`,
									}"
								/>
							</span>
						</div>
					</div>
				</section>

				<!-- The tiers ladder. The rail in the leading column is doing a
				     semantic job, not a wayfinding one: it says "path you're on",
				     where a bare list of prices reads as "menu you pick from".
				     No headings: every value is self-labeling, and the ascending
				     price edge explains itself.

				     Not a table, because the columns can't all survive 375px. Each
				     rung is a wrapping flex row instead, so the three fields reflow:
				     desktop keeps name | requirements | price on one line, and mobile
				     puts name and price on the first line with the requirements —
				     the longest field by far — spanning the full width beneath.
				     Squeezed into a column, "≥ $300.00 paid to date" wrapped to four
				     lines per rung. -->
				<ul class="text-lg sm:text-base">
					<!-- No row dividers: the rail and the row rhythm do the separating,
					     and a hairline would cut across the timeline. -->
					<li v-for="(l, rung) in levels" :key="l.tier" class="flex gap-3">
						<!-- The travelled track is solid and the road ahead is faint;
						     both stop at the first and last dots so the ladder reads
						     bounded rather than running off the end. -->
						<div class="relative w-3 shrink-0" aria-hidden="true">
							<!-- bg-surface-*, not bg-outline-*: outline tokens carry no
							     background value, so a faint line needs a surface tone. -->
							<span
								v-if="rung !== 0"
								class="absolute left-1/2 top-0 h-6 w-px -translate-x-1/2"
								:class="
									l.state === 'locked'
										? 'bg-surface-gray-3'
										: 'bg-surface-gray-5'
								"
							/>
							<span
								v-if="rung !== levels.length - 1"
								class="absolute bottom-0 left-1/2 top-6 w-px -translate-x-1/2"
								:class="
									l.state === 'reached'
										? 'bg-surface-gray-5'
										: 'bg-surface-gray-3'
								"
							/>
							<!-- top-6 = the row's pt-4 (16px) plus half a line box. These
							     tokens are 1.15 line-height, not Tailwind's 1.5, so a 14px
							     name centres at ~24px and a 16px one at ~25px — 24 splits
							     them; 28 sat visibly below the text. -->
							<span
								class="absolute left-1/2 top-6 -translate-x-1/2 -translate-y-1/2 rounded-full"
								:class="DOT_CLASSES[l.state]"
							/>
						</div>

						<!-- Rungs behind you dim as whole rows (the rail stays full
						     strength) so the eye lands on current and next. -->
						<div
							class="flex min-w-0 flex-1 flex-wrap items-start gap-x-4 gap-y-2 py-4"
							:class="l.state === 'reached' ? 'opacity-40' : ''"
						>
							<!-- DOM order is the desktop reading order — name, requirements,
							     price — so the accessibility tree and the tab order match what
							     a sighted desktop user sees (order-* moves neither). Only
							     mobile reorders, and there the visual order it produces is the
							     same sequence read aloud, just wrapped onto two lines. -->
							<span class="order-1 font-semibold text-ink-gray-9 sm:order-none sm:w-28">
								{{ tierLabel(l) }}
							</span>

							<!-- w-full is what forces the wrap on mobile; on desktop it
							     becomes the flexible middle column. -->
							<ul
								class="order-3 flex w-full flex-col gap-1.5 sm:order-none sm:w-auto sm:flex-1"
							>
								<!-- items-start, not items-center: a requirement that wraps to
								     two lines would otherwise float its mark between them. -->
								<li
									v-for="(req, i) in requirementsFor(l)"
									:key="i"
									class="flex items-start gap-2"
								>
									<span
										class="mt-1 size-3.5 shrink-0"
										:class="
											req.met
												? 'lucide-check text-ink-green-5'
												: 'lucide-minus text-ink-gray-4'
										"
										aria-hidden="true"
									/>
									<span :class="req.met ? 'text-ink-gray-9' : 'text-ink-gray-6'">
										{{ req.text }}
									</span>
								</li>
							</ul>

							<!-- order-2 pulls this onto the name's line on mobile; on desktop
							     it falls back to DOM order, which is already last. -->
							<div class="order-2 ml-auto text-right sm:order-none">
								<span
									class="whitespace-nowrap font-semibold tabular-nums text-ink-gray-9"
								>
									{{ money(l.max_spend, currency) }}
								</span>
								<p
									v-if="l.max_resource_count != null"
									class="whitespace-nowrap text-p-md text-ink-gray-5 sm:text-p-sm"
								>
									up to
									{{ l.max_resource_count }}
									resource{{ l.max_resource_count === 1 ? '' : 's' }}
								</p>
							</div>
						</div>
					</li>
				</ul>

				<!-- Same fold as billing's Advanced section. -->
				<section>
					<button
						class="-mx-2 flex items-center gap-1.5 rounded-5 px-2 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
						:aria-expanded="howOpen"
						@click="howOpen = !howOpen"
					>
						<span
							class="lucide-chevron-right size-3.5 shrink-0 text-ink-gray-5 transition-transform duration-150 ease-out"
							:class="howOpen ? 'rotate-90' : ''"
						/>
						<h2 class="text-base-medium text-ink-gray-8">How tiers work</h2>
					</button>
					<ul
						v-if="howOpen"
						class="mt-3 flex list-disc flex-col gap-1.5 pl-4 text-p-base text-ink-gray-6"
					>
					<!-- Defined first — the table above leans on this word. -->
						<li>
							A resource is anything that bills while it runs: a server or a
							subscribed service.
						</li>
						<li>
							Tiers control the maximum amount your team can spend in a billing
							cycle.
						</li>
						<li>
							You move up automatically as your paid invoices and total spend
						cross each tier's bar.
						</li>
						<li>
							New teams start at the base tier. Add a payment method or prepaid
							credits to stay there.
						</li>
						<li>
							Need a higher limit now? Contact
							<a
								href="https://support.frappe.io"
								target="_blank"
								rel="noopener noreferrer"
								class="text-ink-blue-7 underline underline-offset-2 transition-opacity hover:opacity-80"
								>support</a
							>
							and we'll review your account.
						</li>
					</ul>
				</section>
			</template>

			<p v-else class="py-12 text-center text-p-sm text-ink-gray-5">
				Spending tiers aren't configured yet.
			</p>
		</div>

		<!-- The empty state's flow, in place: billing details first when the
		     profile is incomplete, then the add-method dialog. -->
		<EditBillingProfileDialog v-model="setupDialogOpen" />
		<AddMethodDialog v-model="showAddMethod" @done="onMethodAdded" />
	</div>
</template>
