<script setup lang="ts">
import { computed } from 'vue'
import { useCall, Badge, LoadingText } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import type { TrustTier, TierLevel } from '@/types/billing'

// Billing › Limit Tiers, shown to customers as "Spending Limits". A team's tier
// sets how much it can spend and how many resources it can run; paying invoices on
// time promotes it to higher tiers (#07/#08). Backend stays "Trust Tier"; the UI
// shows each rung's own title (Beginner, Growth, …) rather than a "Tier N" derived
// from the sequence. Reads get_trust_tier (current + next + full ladder).
//
// Layout mirrors the frappe-cloud-v2 prototype: a standing band, a tiers table
// whose Requirements column shows each rung's promotion gates against the team's
// live progress, and a "how it works" explainer.
const { activeTeam } = useSession()

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

// Customer-facing rung name: the tier's own title (Beginner, Growth, …), not a
// "Tier N" derived from its sequence.
function tierLabel(level: TierLevel | null | undefined): string {
	if (!level) return '—'
	return level.tier || '—'
}

interface Requirement {
	text: string
	met: boolean
}

// A rung's promotion gates, checked against the team's live progress. The base
// rung has no thresholds — it's where every team starts.
function requirementsFor(level: TierLevel): Requirement[] {
	const p = prog.value
	const paid = Number(p?.paid_invoices ?? 0)
	const cumulative = Number(p?.cumulative_paid ?? 0)
	if (level.sequence <= 0) {
		return [{ text: 'Starting tier — available to every team', met: true }]
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
function hasUnmet(level: TierLevel): boolean {
	return requirementsFor(level).some((r) => !r.met)
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
	<div class="flex h-full flex-col">

		<div class="min-h-0 flex-1 overflow-y-auto">
			<div class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
				<div v-if="tier.loading && !tier.data" class="space-y-3">
					<LoadingText :lines="6" />
				</div>

				<template v-else-if="cur">
					<p class="max-w-2xl text-p-base text-ink-gray-5">
						Your monthly spending limit. You move to a higher tier automatically
						as your usage and payment history grow — which lifts these limits
						and the UPI-Autopay mandate ceiling.
					</p>

					<!-- Current standing -->
					<div
						class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-4"
					>
						<div class="flex flex-wrap items-center justify-between gap-3">
							<div class="flex flex-col gap-1">
								<div class="text-sm text-ink-gray-6">Current tier</div>
								<span
									class="flex items-center gap-2 text-xl font-semibold text-ink-gray-9"
								>
									{{ tierLabel(cur) }}
									<Badge
										v-if="tier.data?.is_top_tier"
										theme="green"
										label="Top tier"
									/>
								</span>
								<div class="text-p-sm text-ink-gray-6">
									Spending limit
									<span class="font-medium text-ink-gray-9"
										>{{ money(cur.max_spend, currency) }}</span
									>
								</div>
							</div>
							<div class="flex flex-col gap-1 text-right">
								<div class="text-sm text-ink-gray-6">
									Paid to date
									<span class="font-medium text-ink-gray-9">
										{{ money(prog?.cumulative_paid, currency) }}
									</span>
								</div>
								<div class="text-sm text-ink-gray-6">
									<span class="font-medium text-ink-gray-9"
										>{{ prog?.paid_invoices ?? 0 }}</span
									>
									paid invoice{{ prog?.paid_invoices === 1 ? '' : 's' }}
								</div>
							</div>
						</div>
					</div>

					<!-- Tiers table -->
					<div
						class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-elevation-1"
					>
						<table class="w-full text-left">
							<thead>
								<tr
									class="border-b border-outline-gray-2 bg-surface-gray-1 text-p-sm text-ink-gray-5"
								>
									<th class="px-4 py-3 font-medium">Tier</th>
									<th class="px-4 py-3 font-medium">Requirements</th>
									<th class="px-4 py-3 text-right font-medium">
										Spending limit
									</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-outline-gray-2">
								<tr
									v-for="l in levels"
									:key="l.tier"
									class="transition-colors hover:bg-surface-gray-1"
									:class="l.state === 'current' && 'bg-surface-gray-1'"
								>
									<td class="px-4 py-4 align-top">
										<div class="flex flex-wrap items-center gap-2">
											<span class="text-sm font-semibold text-ink-gray-9"
												>{{ tierLabel(l) }}</span
											>
											<Badge
												v-if="l.state === 'current'"
												theme="blue"
												label="Current"
											/>
										</div>
									</td>
									<td class="px-4 py-4 align-top">
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
                              ? 'lucide-circle-check text-ink-green-3'
                              : 'lucide-circle-dashed text-ink-gray-4'
                          "
													aria-hidden="true"
												/>
												<span
													class="text-sm"
													:class="req.met ? 'text-ink-gray-9' : 'text-ink-gray-6'"
												>
													{{ req.text }}
												</span>
											</li>
											<li
												v-if="l.state !== 'reached' && l.state !== 'current' && hasUnmet(l)"
											>
												<RouterLink
													:to="{ name: 'Billing' }"
													class="text-sm text-ink-blue-3 transition-opacity hover:opacity-80"
												>
													Go to Billing →
												</RouterLink>
											</li>
										</ul>
									</td>
									<td class="px-4 py-4 text-right align-top">
										<span
											class="text-sm font-semibold tabular-nums text-ink-gray-9"
										>
											{{ money(l.max_spend, currency) }}
										</span>
										<p
											v-if="l.max_resource_count != null"
											class="mt-0.5 text-p-xs text-ink-gray-5"
										>
											up to
											{{ l.max_resource_count }}
											resource{{ l.max_resource_count === 1 ? '' : 's' }}
										</p>
									</td>
								</tr>
							</tbody>
						</table>
					</div>

					<!-- How tiers work -->
					<div
						class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5"
					>
						<div class="flex flex-col gap-2">
							<div class="flex items-center gap-2">
								<span
									class="lucide-info size-5 shrink-0 text-ink-gray-5"
									aria-hidden="true"
								/>
								<div class="text-base font-medium text-ink-gray-9">
									How tier upgrades work
								</div>
							</div>
							<ul
								class="flex list-disc flex-col gap-1.5 pl-5 text-p-sm text-ink-gray-7"
							>
								<li>
									Tiers cap how much your team can spend in a billing cycle and
									how many resources it can run.
								</li>
								<li>
									You're promoted automatically once you've cleared a tier's
									paid-invoice count and its cumulative-paid threshold.
								</li>
								<li>
									New teams start at the base tier — add a payment method or
									prepaid credits to keep running.
								</li>
								<li>
									Need a higher limit now? Contact support and we'll review your
									account.
								</li>
							</ul>
						</div>
					</div>
				</template>

				<div v-else class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
					No spending limit assigned yet.
				</div>
			</div>
		</div>
	</div>
</template>
