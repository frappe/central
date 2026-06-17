<script setup>
import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { Badge, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { money } from '@/utils/money'

// What the team's trust tier offers, and what unlocks the next level. Higher
// tiers raise the spend cap, resource cap and the UPI-Autopay mandate ceiling
// (#07/#08). Promotion is automatic once both gates are cleared.
const { currentTeam } = useTeam()

const tier = useCall({
  url: m(API.trustTier),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

const currency = computed(() => tier.data?.currency || 'INR')
const cur = computed(() => tier.data?.current)
const nxt = computed(() => tier.data?.next)
const prog = computed(() => tier.data?.progress || {})

function pct(used, need) {
  if (!need) return 100
  return Math.min(100, Math.round((Number(used || 0) / Number(need)) * 100))
}

// Each promotion gate, with the team's progress against it.
const gates = computed(() => {
  if (!nxt.value) return []
  return [
    {
      label: 'Paid invoices',
      used: prog.value.paid_invoices,
      need: nxt.value.min_paid_invoices,
      fmt: (v) => Number(v || 0),
    },
    {
      label: 'Cumulative paid',
      used: prog.value.cumulative_paid,
      need: nxt.value.min_cumulative_paid,
      fmt: (v) => money(v, currency.value),
    },
  ].map((g) => ({ ...g, met: Number(g.used || 0) >= Number(g.need || 0) }))
})

// All levels, tagged reached / current / locked relative to where the team is.
const levels = computed(() => {
  const all = tier.data?.all_levels || []
  const ci = all.findIndex((l) => l.tier === cur.value?.tier)
  return all.map((l, i) => ({ ...l, state: i < ci ? 'reached' : i === ci ? 'current' : 'locked' }))
})
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Team' }, { label: 'Trust Tier' }]" />

    <div class="body-container space-y-6 pb-40 pt-5">
      <div v-if="tier.loading && !tier.data" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <template v-else-if="cur">
        <p class="max-w-2xl text-p-sm text-ink-gray-5">
          Your trust tier sets how much your team can spend and how many resources it can run.
          Paying invoices on time promotes you to higher tiers, which lift these limits and the
          UPI-Autopay mandate ceiling.
        </p>

        <!-- Current tier -->
        <section class="rounded-lg border border-outline-gray-1 bg-surface-white p-5">
          <div class="flex items-center justify-between gap-2">
            <div>
              <p class="text-p-sm text-ink-gray-5">Current tier</p>
              <p class="mt-0.5 text-2xl font-medium uppercase text-ink-gray-9">{{ cur.tier }}</p>
            </div>
            <Badge v-if="tier.data.is_top_tier" theme="green" label="Top tier" size="lg" />
          </div>
          <div class="mt-4 grid gap-4 sm:grid-cols-2">
            <StatTile label="Spend cap" :value="money(cur.max_spend, currency)" />
            <StatTile label="Resource cap" :value="String(cur.max_resource_count ?? '—')" />
          </div>
        </section>

        <!-- Progress to next -->
        <section v-if="nxt" class="rounded-lg border border-outline-gray-1 bg-surface-white p-5">
          <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h2 class="text-base text-ink-gray-9">
              Progress to <span class="uppercase">{{ nxt.tier }}</span>
            </h2>
            <span class="text-p-sm text-ink-gray-5">
              Raises spend cap to {{ money(nxt.max_spend, currency) }}
            </span>
          </div>
          <p class="mt-1 text-p-sm text-ink-gray-5">Clear both gates to be promoted automatically.</p>

          <div class="mt-5 space-y-4">
            <div v-for="g in gates" :key="g.label">
              <div class="mb-1.5 flex items-center justify-between text-p-sm">
                <span class="flex items-center gap-1.5 text-ink-gray-7">
                  {{ g.label }}
                  <span v-if="g.met" class="lucide-check size-3.5 text-ink-green-3" aria-hidden="true" />
                </span>
                <span class="tabular-nums text-ink-gray-6">{{ g.fmt(g.used) }} / {{ g.fmt(g.need) }}</span>
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
          class="flex items-center gap-2 rounded-lg border border-outline-gray-1 bg-surface-white px-5 py-4 text-p-sm text-ink-gray-6"
        >
          <span class="lucide-circle-check size-4 text-ink-green-3" aria-hidden="true" />
          You’re at the highest trust tier — the maximum spend and resource headroom.
        </section>

        <!-- All levels -->
        <section class="overflow-hidden rounded-lg border border-outline-gray-1 bg-surface-white">
          <header class="border-b border-outline-gray-1 px-4 py-3">
            <h2 class="text-base text-ink-gray-8">All tiers</h2>
          </header>
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-outline-gray-1 text-left text-p-sm text-ink-gray-5">
                <th class="px-4 py-2 font-normal">Tier</th>
                <th class="px-4 py-2 text-right font-normal">Spend cap</th>
                <th class="px-4 py-2 text-right font-normal">Resources</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-outline-gray-1">
              <tr v-for="l in levels" :key="l.tier" :class="l.state === 'current' && 'bg-surface-gray-1'">
                <td class="px-4 py-2.5">
                  <div class="flex items-center gap-2">
                    <span
                      class="size-4 shrink-0"
                      :class="l.state === 'reached'
                        ? 'lucide-check text-ink-green-3'
                        : l.state === 'locked'
                          ? 'lucide-lock text-ink-gray-4'
                          : 'lucide-circle-dot text-ink-gray-7'"
                      aria-hidden="true"
                    />
                    <span class="uppercase text-ink-gray-8">{{ l.tier }}</span>
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
        No trust tier assigned yet.
      </div>
    </div>
  </div>
</template>
