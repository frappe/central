<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Button } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import MockBanner from '@/components/MockBanner.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { operationalTheme } from '@/utils/status'
import { MOCK_VMS, MOCK_CLUSTERS, clusterLabel } from './mock'

// 🟡 Mock. Single registry of everything the team has provisioned — counts by
// status, cluster breakdown, recent assets. Each asset carries its resource_id
// (the Agent's source-of-truth handle that reconciles with billing line items).
const router = useRouter()
const { canManageAtlas } = useCapabilities()

const counts = computed(() => {
  const c = { running: 0, stopped: 0, terminated: 0 }
  for (const vm of MOCK_VMS) c[vm.status] = (c[vm.status] || 0) + 1
  return c
})

const byCluster = computed(() =>
  MOCK_CLUSTERS.filter((c) => c.resources > 0).map((c) => ({
    label: c.label,
    resources: c.resources,
  })),
)

const recent = computed(() => MOCK_VMS.filter((vm) => vm.status !== 'terminated').slice(0, 6))
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Atlas' }, { label: 'Registry' }]">
      <template #actions>
        <Button v-if="canManageAtlas" variant="solid" label="Provision resource" disabled />
      </template>
    </PageHeader>

    <div class="body-container space-y-6 pb-40 pt-5">
      <MockBanner />

      <div class="grid gap-4 sm:grid-cols-3">
        <StatTile label="Running" :value="String(counts.running)" />
        <StatTile label="Stopped" :value="String(counts.stopped)" />
        <StatTile label="Terminated" :value="String(counts.terminated)" />
      </div>

      <section class="rounded border border-outline-gray-1 px-4 py-3">
        <h2 class="text-base text-ink-gray-8">By cluster</h2>
        <ul class="mt-2 space-y-1.5">
          <li v-for="c in byCluster" :key="c.label" class="flex items-center gap-3">
            <span class="w-44 shrink-0 text-sm text-ink-gray-7">{{ c.label }}</span>
            <div class="h-2 flex-1 overflow-hidden rounded bg-surface-gray-2">
              <div class="h-full rounded bg-surface-gray-5" :style="{ width: `${c.resources * 20}%` }" />
            </div>
            <span class="w-6 text-right text-p-sm text-ink-gray-6">{{ c.resources }}</span>
          </li>
        </ul>
      </section>

      <section class="rounded border border-outline-gray-1">
        <header class="border-b border-outline-gray-1 px-4 py-3">
          <h2 class="text-base text-ink-gray-8">Recent assets</h2>
        </header>
        <ul class="divide-y divide-outline-gray-1">
          <li
            v-for="vm in recent"
            :key="vm.resource_id"
            class="flex items-center justify-between gap-3 px-4 py-3"
          >
            <div class="min-w-0">
              <p class="truncate text-sm text-ink-gray-8">{{ vm.name }}</p>
              <p class="text-p-sm text-ink-gray-5">
                VM · {{ clusterLabel(vm.cluster) }} · {{ vm.resource_id }}
              </p>
            </div>
            <div class="flex items-center gap-3">
              <Badge :theme="operationalTheme(vm.status)" :label="vm.status" />
              <Button variant="ghost" label="Open" @click="router.push({ name: 'AtlasVMs' })" />
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
