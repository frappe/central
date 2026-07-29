<script setup lang="ts">
import { computed } from 'vue'
import { useCall, Badge, LoadingText } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { money } from '@/lib/format'
import type { TrustTier, TierLevel } from '@/types/billing'

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

const currency = computed(() => tier.data?.currency || 'INR')
const cur = computed(() => tier.data?.current)
const prog = computed(() => tier.data?.progress)
const monthlySpend = computed(() => forecast.data?.projected_total)

// Whole months since the team's first paid invoice, for the "Paying since" stat.
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

const tierLabel = (level: TierLevel | null | undefined): string => {
	if (!level) return '—'
	return level.tier || '—'
}

interface Requirement {
	text: string
	met: boolean
	nudge?: boolean
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
		return [
			{
				text: 'Payment method added or prepaid credits available',
				met,
				nudge: !met,
			},
		]
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
	<div class="h-full overflow-y-auto">
		<div class="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-8">
			<LoadingText v-if="tier.loading && !tier.data" :lines="6" />

			<template v-else-if="levels.length">
				<div class="flex flex-col gap-1">
					<h1 class="text-xl font-semibold text-ink-gray-9">Spending limits</h1>

					<p class="text-p-base text-ink-gray-5">
						Your monthly spending limit. You move to a higher tier automatically
						as your usage and payment history grow.
					</p>
				</div>

				<!-- Current spending stats -->
				<div class="flex flex-wrap gap-x-12 gap-y-4 leading-relaxed">
					<div class="flex flex-col gap-1">
						<span class="text-sm text-ink-gray-5">Monthly spend</span>
						<span class="text-xl font-semibold tabular-nums text-ink-gray-9">
							{{ money(monthlySpend, currency, { trimTrailingZeros: true }) }}
						</span>
					</div>

					<div class="flex flex-col gap-1">
						<span class="text-sm text-ink-gray-5">Paying since</span>
						<span class="text-xl font-semibold text-ink-gray-9"
							>{{ payingSince ?? '—' }}
						</span>
					</div>

					<div class="flex flex-col gap-1">
						<span class="text-sm text-ink-gray-5">Last paid invoice</span>
						<span class="text-xl font-semibold tabular-nums text-ink-gray-9">
							{{ money(prog?.last_paid_invoice_amount, currency, { trimTrailingZeros: true }) }}
						</span>
					</div>
				</div>

				<!-- Tiers table -->
				<table class="w-full text-left text-sm">
					<thead>
						<tr
							class="border-b border-outline-gray-2 text-p-sm text-ink-gray-5"
						>
							<th class="w-28 py-2 font-medium">Tier</th>
							<th class="py-2 font-medium">Requirements</th>
							<th class="py-2 text-right font-medium">Spending limit</th>
						</tr>
					</thead>

					<tbody>
						<tr
							v-for="l in levels"
							:key="l.tier"
							class="border-b border-outline-gray-1 last:border-b-0"
						>
							<td>
								<span class="font-semibold text-ink-gray-9">
									{{ tierLabel(l) }}
								</span>
								<Badge
									v-if="l.state === 'current'"
									class="ml-2"
									theme="blue"
									label="Current"
								/>
							</td>

							<td>
								<ul class="flex flex-col gap-1.5">
									<li
										v-for="(req, i) in requirementsFor(l)"
										:key="i"
										class="flex items-center gap-2"
									>
										<span
											class="size-3.5 shrink-0"
											:class="
                          req.met
                            ? 'lucide-circle-check text-ink-green-6'
                            : 'lucide-circle-dashed text-ink-gray-4'
                        "
											aria-hidden="true"
										/>
										<span
											:class="req.met ? 'text-ink-gray-9' : 'text-ink-gray-6'"
										>
											{{ req.text }}
										</span>

										<router-link
											v-if="req.nudge"
											:to="{ name: 'Billing' }"
											class="hover:underline-offset-4 hover:underline"
										>
											Go to Billing →
										</router-link>
									</li>
								</ul>
							</td>

							<td class="text-right">
								<span class="font-semibold tabular-nums text-ink-gray-9">
									{{ money(l.max_spend, currency) }}
								</span>
								<p
									v-if="l.max_resource_count != null"
									class="text-p-xs text-ink-gray-5"
								>
									up to
									{{ l.max_resource_count }}
									resource{{ l.max_resource_count === 1 ? '' : 's' }}
								</p>
							</td>
						</tr>
					</tbody>
				</table>

				<section class="border-t border-outline-gray-1 pt-6">
					<h2 class="text-base font-medium text-ink-gray-9">
						How tier upgrades work
					</h2>
					<ul
						class="mt-2.5 flex list-disc flex-col gap-1.5 pl-4 text-p-sm text-ink-gray-6"
					>
						<li>
							Tiers control the maximum amount your team can spend in a billing
							cycle.
						</li>
						<li>
							You're automatically upgraded once you clear a tier's paid-invoice
							count and cumulative-paid thresholds — each tier sets its own bar.
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
								class="text-ink-blue-8 underline underline-offset-2 transition-opacity hover:opacity-80"
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
	</div>
</template>

<style scoped>
td {
	padding-top: 0.875rem;
	padding-bottom: 0.875rem;
	vertical-align: top;
}
</style>
