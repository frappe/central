<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Dialog, LoadingIndicator, Tooltip, useCall } from 'frappe-ui'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { configIncludes, configSpecs, estimateConfig } from '@/lib/composed'
import { money } from '@/lib/format'
import type { AssetRow } from '@/composables/useServers'
import type { ComposedConfig, ProvisionablePlans, RateCard } from '@/types/api'

// Resize a server with the very same slider used to design it (#82/#84). Works for
// both a composed server and a preset one (resizing a preset slides it onto a custom
// config). Firecracker can't reconfigure a running machine, so the VM must be Stopped
// first — a live one shows a turn-off prompt (DO-style) with Resize disabled.
// Controlled by the page via v-model:server; the page owns the stop call and keeps
// `server` pointing at the live mirror row, so the dialog reacts as the VM stops.
const props = defineProps<{ server: AssetRow | null; stopping?: boolean }>()
const emit = defineEmits<{
  'update:server': [server: AssetRow | null]
  resized: []
  stop: [server: AssetRow]
}>()

const { activeTeam } = useSession()

const open = computed({
  get: () => !!props.server,
  set: (v: boolean) => {
    // Don't let a stray close (Esc / backdrop) abandon an in-flight resize.
    if (!v && !resizeCall.loading) emit('update:server', null)
  },
})

// The VM must be off to reshape it (Firecracker is pre-boot only) — the same gate
// the server enforces. A terminated server can't resize at all.
const isStopped = computed(() => props.server?.status === 'Stopped')
const isDead = computed(() => props.server?.status === 'Terminated')

// The running config + its resize headroom (cap minus the team's *other* run-rate).
type ComposedConfigResponse = {
  resizable: boolean
  composed?: boolean
  subscription?: string
  sub_category?: string | null
  vcpus?: number
  memory_gb?: number
  disk_gb?: number
  available?: number
}
const configCall = useCall<ComposedConfigResponse, { asset: string; team: string }>({
  url: method(API.composedConfig),
  // params is tracked eagerly, so stay null-safe while the dialog is closed
  // (server is null); reload() only fires once a server is set (see watch below).
  params: () => ({ asset: props.server?.resource_id ?? '', team: activeTeam.value ?? '' }),
  immediate: false,
})
// The region's rate card + profile bounds the slider needs.
const plansCall = useCall<ProvisionablePlans, { team: string; cluster: string }>({
  url: method(API.eligiblePlans),
  params: () => ({ team: activeTeam.value ?? '', cluster: props.server?.cluster ?? '' }),
  immediate: false,
})

watch(
  () => props.server,
  (server) => {
    chosen.value = null
    if (server && activeTeam.value) {
      configCall.reload()
      plansCall.reload()
    }
  },
)

const resizable = computed(() => configCall.data?.resizable === true)
// Pre-fill the designer from the running shape. A preset carries no profile, so we
// default to the region's first — resizing it slides it onto a custom config.
const initial = computed<ComposedConfig | null>(() =>
  resizable.value
    ? {
        sub_category: configCall.data!.sub_category ?? plansCall.data?.profiles?.[0]?.sub_category ?? '',
        vcpus: configCall.data!.vcpus ?? 0,
        memory_gb: configCall.data!.memory_gb ?? 0,
        disk_gb: configCall.data!.disk_gb ?? 0,
      }
    : null,
)
const rateCard = computed<RateCard>(() => plansCall.data?.rate_card ?? {})
const currency = computed(() => plansCall.data?.currency ?? 'USD')

const chosen = ref<ComposedConfig | null>(null)
const currentEstimate = computed(() => (initial.value ? estimateConfig(initial.value, rateCard.value) : 0))
const newEstimate = computed(() => (chosen.value ? estimateConfig(chosen.value, rateCard.value) : 0))
// A confirm is meaningful only when the shape actually changed.
const changed = computed(
  () =>
    !!chosen.value &&
    !!initial.value &&
    (chosen.value.vcpus !== initial.value.vcpus ||
      chosen.value.disk_gb !== initial.value.disk_gb ||
      chosen.value.sub_category !== initial.value.sub_category),
)

type ResizeParams = {
  subscription: string
  includes: { resource_type: string; quantity: number; unit: string }[]
  sub_category: string
}
const resizeCall = useCall<{ subscription: string; resized: boolean }, ResizeParams>({
  url: method(API.resizeComposedConfig),
  method: 'POST',
  immediate: false,
})

async function confirm() {
  if (!chosen.value || !configCall.data?.subscription) return
  await resizeCall.submit({
    subscription: configCall.data.subscription,
    includes: configIncludes(chosen.value),
    sub_category: chosen.value.sub_category,
  })
  if (!resizeCall.error) {
    emit('resized')
    open.value = false
  }
}

// Ask the page to stop the server, but stay open — Resize unlocks in place once the
// mirror reports it Stopped (the page keeps `server` pointed at the live row).
function turnOff() {
  if (props.server) emit('stop', props.server)
}
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Resize server' }">
    <template #body-content>
      <!-- Resize runs on the host and can take a while for a data-heavy server, so
           show a clear in-progress state and hold the dialog open until it lands. -->
      <div v-if="resizeCall.loading" class="flex flex-col items-center gap-3 py-10 text-center">
        <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
        <p class="text-p-base font-medium text-ink-gray-8">Resizing your server…</p>
        <p class="max-w-xs text-p-sm text-ink-gray-5">
          This can take a few minutes for a server with a lot of data. It'll start back up on its own
          once done — keep this window open.
        </p>
      </div>
      <p v-else-if="configCall.loading || plansCall.loading" class="text-p-sm text-ink-gray-5">Loading…</p>
      <p v-else-if="isDead || !resizable" class="text-p-sm text-ink-gray-5">
        This server can't be resized.
      </p>
      <div v-else class="space-y-5">
        <div
          v-if="!isStopped"
          class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-3 py-2.5 text-p-sm text-ink-gray-6"
        >
          Turn off this server to resize its compute resources.
        </div>
        <ConfigDesigner
          v-model="chosen"
          :profiles="plansCall.data?.profiles ?? []"
          :rate-card="rateCard"
          :available="configCall.data?.available ?? 0"
          :initial="initial"
        />
        <div class="flex items-center justify-between rounded-lg bg-surface-gray-1 px-3 py-2 text-p-sm">
          <span class="text-ink-gray-6">
            Now: {{ initial ? configSpecs(initial, rateCard.Disk?.unit) : '—' }} ·
            {{ money(currentEstimate, currency) }}/mo
          </span>
          <span class="font-medium text-ink-gray-9">
            New: {{ money(newEstimate, currency) }}/mo
          </span>
        </div>
      </div>
    </template>
    <template #actions>
      <div v-if="resizable && !isDead && !resizeCall.loading" class="flex items-center justify-end gap-2">
        <Button
          v-if="!isStopped"
          theme="red"
          variant="subtle"
          label="Turn off this server"
          :loading="stopping"
          @click="turnOff"
        />
        <Tooltip :text="isStopped ? '' : 'Turn off this server first'" :disabled="isStopped">
          <Button variant="solid" label="Resize" :disabled="!changed || !isStopped" @click="confirm" />
        </Tooltip>
      </div>
    </template>
  </Dialog>
</template>
