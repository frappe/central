<script setup>
import { computed, ref } from 'vue'
import { Badge, Button, useCall } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeam } from '@/composables/useTeam'
import { operationalTheme } from '@/utils/status'
import { API, m } from '@/api/endpoints'

// Live registry: the team's VMs mirrored from every Atlas cluster, grouped by
// cluster. "Open" mints a scoped SSO assertion and redirects into that VM's bench.
const { currentTeam } = useTeam()
const { has } = useCapabilities()

const registry = useCall({
  url: m(API.atlasRegistry),
  method: 'POST',
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

const assets = computed(() => registry.data?.assets ?? [])
const stale = computed(() => registry.data?.stale ?? [])
const canOpen = computed(() => has('vm:open'))

const counts = computed(() => {
  const c = { Running: 0, Stopped: 0, Terminated: 0 }
  for (const a of assets.value) c[a.status] = (c[a.status] || 0) + 1
  return c
})

const clusters = computed(() => {
  const map = {}
  for (const a of assets.value) (map[a.cluster] ||= []).push(a)
  return Object.entries(map).map(([cluster, vms]) => ({ cluster, vms }))
})

const opening = ref('')
const openCall = useCall({ url: m(API.getBenchLink), method: 'GET', immediate: false })

async function openVm(asset) {
  opening.value = asset.resource_id
  try {
    const res = await openCall.submit({ asset: asset.resource_id })
    if (res?.url) window.location.href = res.url
  } finally {
    opening.value = ''
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Atlas' }, { label: 'Registry' }]" />

    <div class="body-container space-y-6 pb-40 pt-5">
      <p v-if="stale.length" class="rounded bg-surface-amber-1 px-3 py-2 text-p-sm text-ink-amber-3">
        Showing last-known data — couldn't reach: {{ stale.join(', ') }}
      </p>

      <div class="grid gap-4 sm:grid-cols-3">
        <StatTile label="Running" :value="String(counts.Running)" />
        <StatTile label="Stopped" :value="String(counts.Stopped)" />
        <StatTile label="Terminated" :value="String(counts.Terminated)" />
      </div>

      <p v-if="!registry.loading && !assets.length" class="text-sm text-ink-gray-5">
        No VMs for this team yet.
      </p>

      <section
        v-for="group in clusters"
        :key="group.cluster"
        class="rounded border border-outline-gray-1"
      >
        <header class="border-b border-outline-gray-1 px-4 py-3">
          <h2 class="text-base text-ink-gray-8">{{ group.cluster }}</h2>
        </header>
        <ul class="divide-y divide-outline-gray-1">
          <li
            v-for="vm in group.vms"
            :key="vm.resource_id"
            class="flex items-center justify-between gap-3 px-4 py-3"
          >
            <div class="min-w-0">
              <p class="truncate text-sm text-ink-gray-8">{{ vm.resource_id }}</p>
              <p class="text-p-sm text-ink-gray-5">VM · {{ group.cluster }}</p>
            </div>
            <div class="flex items-center gap-3">
              <Badge :theme="operationalTheme(vm.status.toLowerCase())" :label="vm.status" />
              <Button
                v-if="canOpen"
                variant="ghost"
                label="Open"
                :loading="opening === vm.resource_id"
                :disabled="vm.status !== 'Running' || !vm.gateway_url"
                @click="openVm(vm)"
              />
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
