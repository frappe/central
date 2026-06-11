<script setup>
import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { Badge, Progress, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { money } from '@/utils/money'

// What the team's trust tier offers, and what unlocks the next level. Higher
// tiers raise the spend cap and the UPI-Autopay mandate ceiling (#07/#08).
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
      fmt: (v) => v,
    },
    {
      label: 'Cumulative paid',
      used: prog.value.cumulative_paid,
      need: nxt.value.min_cumulative_paid,
      fmt: (v) => money(v, currency.value),
    },
  ]
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
        <!-- Current tier -->
        <div class="rounded border border-outline-gray-1 px-5 py-4">
          <div class="flex items-center justify-between gap-2">
            <div>
              <p class="text-sm text-ink-gray-5">Current tier</p>
              <p class="mt-1 text-2xl text-ink-gray-9">{{ cur.tier }}</p>
            </div>
            <Badge v-if="tier.data.is_top_tier" theme="green" label="Top tier" size="lg" />
          </div>
          <div class="mt-4 grid gap-4 sm:grid-cols-2">
            <StatTile label="Spend cap" :value="money(cur.max_spend, currency)" />
            <StatTile label="Resource cap" :value="String(cur.max_resource_count ?? '—')" />
          </div>
        </div>

        <!-- Progress to next -->
        <section v-if="nxt" class="rounded border border-outline-gray-1 px-5 py-4">
          <div class="flex items-center justify-between">
            <h2 class="text-base text-ink-gray-9">Next: {{ nxt.tier }}</h2>
            <span class="text-p-sm text-ink-gray-5">
              raises spend cap to {{ money(nxt.max_spend, currency) }}
            </span>
          </div>
          <div class="mt-4 space-y-4">
            <div v-for="g in gates" :key="g.label">
              <div class="mb-1 flex justify-between text-p-sm">
                <span class="text-ink-gray-6">{{ g.label }}</span>
                <span class="text-ink-gray-7">{{ g.fmt(g.used) }} / {{ g.fmt(g.need) }}</span>
              </div>
              <Progress :value="pct(g.used, g.need)" size="sm" />
            </div>
          </div>
        </section>

        <p v-else class="text-p-sm text-ink-gray-5">
          You’re at the highest trust tier — the maximum spend and resource headroom.
        </p>

        <!-- All levels -->
        <section class="rounded border border-outline-gray-1">
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
              <tr
                v-for="l in tier.data.all_levels"
                :key="l.tier"
                :class="l.tier === cur.tier && 'bg-surface-gray-1'"
              >
                <td class="px-4 py-2 text-ink-gray-8">
                  {{ l.tier }}
                  <Badge v-if="l.tier === cur.tier" theme="blue" label="Current" class="ml-1" />
                </td>
                <td class="px-4 py-2 text-right text-ink-gray-7">{{ money(l.max_spend, currency) }}</td>
                <td class="px-4 py-2 text-right text-ink-gray-7">{{ l.max_resource_count ?? '—' }}</td>
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
