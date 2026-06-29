<script setup lang="ts">
import { computed } from 'vue'
import { useCall, Badge, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import type { TrustTier, TierLevel } from '@/types/billing'

// Billing › Limit Tiers, shown to customers as "Spending Limits". A team's tier
// sets how much it can spend and how many resources it can run; paying invoices on
// time promotes it to higher tiers (#07/#08). Backend stays "Trust Tier"; the UI
// speaks Spending Limits / Base / Tier 1–3 (mapped from the rung's sequence, never
// the internal t0…t3 slug). Reads get_trust_tier (current + next + full ladder).
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
const nxt = computed(() => tier.data?.next)
const prog = computed(() => tier.data?.progress)

// Customer-facing rung name from the sequence: Base, then Tier 1, Tier 2, …
function tierLabel(level: TierLevel | null | undefined): string {
  if (!level) return '—'
  return level.sequence <= 0 ? 'Base' : `Tier ${level.sequence}`
}

function pct(used: number | null | undefined, need: number | null | undefined): number {
  if (!need) return 100
  return Math.min(100, Math.round((Number(used || 0) / Number(need)) * 100))
}

// Each promotion requirement, with the team's progress and met/unmet state.
const gates = computed(() => {
  if (!nxt.value || !prog.value) return []
  return [
    {
      label: 'Paid invoices',
      used: prog.value.paid_invoices,
      need: nxt.value.min_paid_invoices ?? 0,
      fmt: (v: number | null | undefined) => String(Number(v || 0)),
    },
    {
      label: 'Cumulative paid',
      used: prog.value.cumulative_paid,
      need: nxt.value.min_cumulative_paid ?? 0,
      fmt: (v: number | null | undefined) => money(v, currency.value),
    },
  ].map((g) => ({ ...g, met: Number(g.used || 0) >= Number(g.need || 0) }))
})

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
    <PageHeader title="Spending Limits" subtitle="Billing" />

    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto w-full max-w-3xl space-y-6 px-5 py-6">
        <div v-if="tier.loading && !tier.data" class="space-y-3">
          <LoadingText :lines="6" />
        </div>

        <template v-else-if="cur">
          <p class="max-w-2xl text-p-sm text-ink-gray-5">
            Your spending limit sets how much your team can spend and how many resources it can
            run. Paying invoices on time raises your limit tier, which lifts these limits and the
            UPI-Autopay mandate ceiling.
          </p>

          <!-- Summary band -->
          <section class="grid gap-4 sm:grid-cols-3">
            <div class="rounded-lg border border-outline-gray-2 bg-surface-white p-4">
              <p class="text-p-sm text-ink-gray-5">Current tier</p>
              <p class="mt-0.5 flex items-center gap-2 text-xl font-medium text-ink-gray-9">
                {{ tierLabel(cur) }}
                <Badge v-if="tier.data?.is_top_tier" theme="green" label="Top tier" />
              </p>
            </div>
            <div class="rounded-lg border border-outline-gray-2 bg-surface-white p-4">
              <p class="text-p-sm text-ink-gray-5">Spending limit</p>
              <p class="mt-0.5 text-xl font-medium tabular-nums text-ink-gray-9">
                {{ money(cur.max_spend, currency) }}
              </p>
            </div>
            <div class="rounded-lg border border-outline-gray-2 bg-surface-white p-4">
              <p class="text-p-sm text-ink-gray-5">Paid to date</p>
              <p class="mt-0.5 text-xl font-medium tabular-nums text-ink-gray-9">
                {{ money(prog?.cumulative_paid, currency) }}
              </p>
              <p class="mt-0.5 text-p-sm text-ink-gray-5">
                {{ prog?.paid_invoices ?? 0 }} paid invoice{{ prog?.paid_invoices === 1 ? '' : 's' }}
              </p>
            </div>
          </section>

          <!-- Progress to next tier -->
          <section v-if="nxt" class="rounded-lg border border-outline-gray-2 bg-surface-white p-5">
            <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h2 class="text-base text-ink-gray-9">Progress to {{ tierLabel(nxt) }}</h2>
              <span class="text-p-sm text-ink-gray-5">
                Raises your limit to {{ money(nxt.max_spend, currency) }}
              </span>
            </div>
            <p class="mt-1 text-p-sm text-ink-gray-5">
              Clear both requirements to be promoted automatically.
            </p>

            <div class="mt-5 space-y-4">
              <div v-for="g in gates" :key="g.label">
                <div class="mb-1.5 flex items-center justify-between text-p-sm">
                  <span class="flex items-center gap-1.5 text-ink-gray-7">
                    {{ g.label }}
                    <span
                      v-if="g.met"
                      class="lucide-check size-3.5 text-ink-green-3"
                      aria-hidden="true"
                    />
                  </span>
                  <span class="tabular-nums text-ink-gray-6">
                    {{ g.fmt(g.used) }} / {{ g.fmt(g.need) }}
                  </span>
                </div>
                <div class="h-2 overflow-hidden rounded-full bg-surface-gray-3">
                  <div
                    class="h-full rounded-full transition-all duration-500 ease-out"
                    :class="g.met ? 'bg-surface-green-5' : 'bg-surface-gray-5'"
                    :style="{ width: `${pct(g.used, g.need)}%` }"
                  />
                </div>
              </div>
            </div>
          </section>

          <section
            v-else
            class="flex items-center gap-2 rounded-lg border border-outline-gray-2 bg-surface-white px-5 py-4 text-p-sm text-ink-gray-6"
          >
            <span class="lucide-circle-check size-4 text-ink-green-3" aria-hidden="true" />
            You're at the highest tier — the maximum spend and resource headroom.
          </section>

          <!-- Full ladder -->
          <section class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white">
            <header class="border-b border-outline-gray-1 px-4 py-3">
              <h2 class="text-base text-ink-gray-8">All tiers</h2>
            </header>
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-outline-gray-1 text-left text-p-sm text-ink-gray-5">
                  <th class="px-4 py-2 font-normal">Tier</th>
                  <th class="px-4 py-2 text-right font-normal">Spending limit</th>
                  <th class="px-4 py-2 text-right font-normal">Resources</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-outline-gray-1">
                <tr
                  v-for="l in levels"
                  :key="l.tier"
                  :class="l.state === 'current' && 'bg-surface-gray-1'"
                >
                  <td class="px-4 py-2.5">
                    <div class="flex items-center gap-2">
                      <span
                        class="size-4 shrink-0"
                        :class="
                          l.state === 'reached'
                            ? 'lucide-check text-ink-green-3'
                            : l.state === 'locked'
                              ? 'lucide-lock text-ink-gray-4'
                              : 'lucide-circle-dot text-ink-gray-7'
                        "
                        aria-hidden="true"
                      />
                      <span class="text-ink-gray-8">{{ tierLabel(l) }}</span>
                      <Badge v-if="l.state === 'current'" theme="blue" label="Current" />
                    </div>
                  </td>
                  <td class="px-4 py-2.5 text-right tabular-nums text-ink-gray-7">
                    {{ money(l.max_spend, currency) }}
                  </td>
                  <td class="px-4 py-2.5 text-right tabular-nums text-ink-gray-7">
                    {{ l.max_resource_count ?? '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>

        <div v-else class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
          No spending limit assigned yet.
        </div>
      </div>
    </div>
  </div>
</template>
