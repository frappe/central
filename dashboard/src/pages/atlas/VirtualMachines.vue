<script setup>
import { ref, computed } from 'vue'
import { Badge, Button, Dropdown, TextInput, Select, TabButtons } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import SplitView from '@/components/SplitView.vue'
import MockBanner from '@/components/MockBanner.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { operationalTheme } from '@/utils/status'
import { infoToast } from '@/utils/toast'
import { MOCK_VMS, MOCK_CLUSTERS, MOCK_EVENTS, clusterLabel } from './mock'

// 🟡 Mock. VM list (split view) + detail tabs. Lifecycle actions are proposed
// endpoints — they toast a notice instead of mutating (no Atlas API yet).
const { canManageAtlas } = useCapabilities()
const { requireSetup } = useBillingSetup()

// Provisioning a VM spends money, so it's gated on a complete billing profile:
// requireSetup() diverts to onboarding (remembering this page) when it isn't.
function onNewVM() {
  if (requireSetup()) action('Create VM')
}

const vms = ref(MOCK_VMS)
const search = ref('')
const cluster = ref('all')
const status = ref('all')

const clusterOptions = [
  { label: 'All clusters', value: 'all' },
  ...MOCK_CLUSTERS.map((c) => ({ label: c.label, value: c.slug })),
]
const statusTabs = [
  { label: 'All', value: 'all' },
  { label: 'Running', value: 'running' },
  { label: 'Stopped', value: 'stopped' },
  { label: 'Terminated', value: 'terminated' },
]

const rows = computed(() => {
  let list = vms.value
  if (cluster.value !== 'all') list = list.filter((v) => v.cluster === cluster.value)
  if (status.value !== 'all') list = list.filter((v) => v.status === status.value)
  const q = search.value.trim().toLowerCase()
  if (q) list = list.filter((v) => v.name.toLowerCase().includes(q) || (v.ip || '').includes(q))
  return list
})

const selected = ref(null)
const detailOpen = computed({
  get: () => !!selected.value,
  set: (v) => { if (!v) selected.value = null },
})
const detailTab = ref('details')
function selectRow(vm) {
  selected.value = vm
  detailTab.value = 'details'
}
const events = computed(() => (selected.value ? MOCK_EVENTS[selected.value.resource_id] || [] : []))

function action(label) {
  infoToast(`${label} isn’t wired yet — Atlas VM actions are a proposed endpoint.`)
}
function rowActions(vm) {
  const a = []
  if (vm.status !== 'running') a.push({ label: 'Start', onClick: () => action('Start') })
  if (vm.status === 'running') a.push({ label: 'Stop', onClick: () => action('Stop') })
  a.push({ label: 'Open console', onClick: () => action('Open console') })
  if (vm.status !== 'terminated') a.push({ label: 'Terminate', onClick: () => action('Terminate') })
  return a
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Atlas' }, { label: 'Virtual Machines' }]">
      <template #actions>
        <Button v-if="canManageAtlas" variant="solid" label="New VM" @click="onNewVM" />
      </template>
    </PageHeader>

    <div class="px-4 pt-3"><MockBanner /></div>

    <SplitView v-model:open="detailOpen" class="flex-1">
      <template #list>
        <div class="flex flex-wrap items-center gap-3 border-b border-outline-gray-1 px-4 py-3">
          <TextInput v-model="search" type="text" placeholder="Search name or IP…" class="w-full sm:w-56">
            <template #prefix><span class="lucide-search size-4 text-ink-gray-5" /></template>
          </TextInput>
          <Select v-model="cluster" :options="clusterOptions" />
          <TabButtons v-model="status" :buttons="statusTabs" />
        </div>

        <div v-if="!rows.length" class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
          No VMs match.
        </div>
        <ul v-else class="divide-y divide-outline-gray-1">
          <li
            v-for="vm in rows"
            :key="vm.resource_id"
            class="flex cursor-pointer items-center gap-3 px-4 py-3 hover:bg-surface-gray-1"
            :class="selected?.resource_id === vm.resource_id && 'bg-surface-gray-2'"
            @click="selectRow(vm)"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm text-ink-gray-8">{{ vm.name }}</p>
              <p class="text-p-sm text-ink-gray-5">
                {{ clusterLabel(vm.cluster) }} · {{ vm.plan }} · {{ vm.vcpu }} vCPU / {{ vm.ram_gb }} GB
                <span v-if="vm.ip"> · {{ vm.ip }}</span>
              </p>
            </div>
            <Badge :theme="operationalTheme(vm.status)" :label="vm.status" />
            <Dropdown v-if="canManageAtlas" :options="rowActions(vm)" placement="right" @click.stop>
              <Button variant="ghost"><template #icon><span class="lucide-ellipsis size-4" /></template></Button>
            </Dropdown>
          </li>
        </ul>
      </template>

      <template #detail>
        <div v-if="selected" class="flex flex-col gap-4 p-4">
          <header class="flex items-center justify-between gap-2">
            <h2 class="text-base text-ink-gray-9">{{ selected.name }}</h2>
            <Badge :theme="operationalTheme(selected.status)" :label="selected.status" />
          </header>

          <TabButtons
            v-model="detailTab"
            :buttons="[{ label: 'Details', value: 'details' }, { label: 'Activity', value: 'activity' }]"
          />

          <dl v-if="detailTab === 'details'" class="space-y-2 text-sm">
            <div class="flex justify-between"><dt class="text-ink-gray-5">Resource ID</dt><dd class="text-ink-gray-8">{{ selected.resource_id }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-gray-5">Cluster</dt><dd class="text-ink-gray-8">{{ clusterLabel(selected.cluster) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-gray-5">Plan</dt><dd class="text-ink-gray-8">{{ selected.plan }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-gray-5">Compute</dt><dd class="text-ink-gray-8">{{ selected.vcpu }} vCPU · {{ selected.ram_gb }} GB</dd></div>
            <div class="flex justify-between"><dt class="text-ink-gray-5">IP</dt><dd class="text-ink-gray-8">{{ selected.ip || '—' }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-gray-5">Created</dt><dd class="text-ink-gray-8">{{ selected.created }}</dd></div>
          </dl>

          <ul v-else class="space-y-2">
            <li v-for="(e, i) in events" :key="i" class="flex gap-3 text-sm">
              <span class="w-24 shrink-0 text-p-sm text-ink-gray-5">{{ e.at }}</span>
              <span class="text-ink-gray-8">{{ e.event }}</span>
              <span class="text-p-sm text-ink-gray-5">{{ e.detail }}</span>
            </li>
            <li v-if="!events.length" class="text-p-sm text-ink-gray-5">No recorded activity.</li>
          </ul>

          <div v-if="canManageAtlas" class="flex gap-2">
            <Button
              v-if="selected.status === 'running'"
              variant="subtle"
              label="Stop"
              @click="action('Stop')"
            />
            <Button
              v-else-if="selected.status === 'stopped'"
              variant="subtle"
              label="Start"
              @click="action('Start')"
            />
            <Button variant="subtle" label="Console" @click="action('Open console')" />
          </div>
        </div>
      </template>
    </SplitView>
  </div>
</template>
