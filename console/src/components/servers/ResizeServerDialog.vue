<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Dialog, useCall } from 'frappe-ui'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { configIncludes, configSpecs, estimateConfig } from '@/lib/composed'
import { formatMoney } from '@/lib/plans'
import type { AssetRow } from '@/composables/useServers'
import type { ComposedConfig, ProvisionablePlans, RateCard } from '@/types/api'

// Resize a running server with the very same slider used to design it (#82/#84).
// Pre-fills the current config, shows old-vs-new, and on confirm drives the
// changed-event re-lock. Controlled by the page via v-model:server.
const props = defineProps<{ server: AssetRow | null }>()
const emit = defineEmits<{ 'update:server': [server: AssetRow | null]; resized: [] }>()

const { activeTeam } = useSession()

const open = computed({
  get: () => !!props.server,
  set: (v: boolean) => {
    if (!v) emit('update:server', null)
  },
})

// The running config + its resize headroom (cap minus the team's *other* run-rate).
type ComposedConfigResponse = {
  composed: boolean
  subscription?: string
  sub_category?: string
  vcpus?: number
  memory_gb?: number
  disk_gb?: number
  available?: number
}
const configCall = useCall<ComposedConfigResponse, { asset: string; team: string }>({
  url: method(API.composedConfig),
  params: () => ({ asset: props.server!.resource_id, team: activeTeam.value! }),
  immediate: false,
})
// The region's rate card + profile bounds the slider needs.
const plansCall = useCall<ProvisionablePlans, { team: string; cluster: string }>({
  url: method(API.eligiblePlans),
  params: () => ({ team: activeTeam.value!, cluster: props.server!.cluster }),
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

const isComposed = computed(() => configCall.data?.composed === true)
const initial = computed<ComposedConfig | null>(() =>
  isComposed.value
    ? {
        sub_category: configCall.data!.sub_category!,
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

const resizeCall = useCall({ url: method(API.resizeComposedConfig), method: 'POST', immediate: false })

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
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Resize server' }">
    <template #body-content>
      <p v-if="configCall.loading || plansCall.loading" class="text-p-sm text-ink-gray-5">Loading…</p>
      <p v-else-if="!isComposed" class="text-p-sm text-ink-gray-5">
        This server runs a preset plan — switch it to a custom config from a new server for now.
      </p>
      <div v-else class="space-y-5">
        <ConfigDesigner
          v-model="chosen"
          :profiles="plansCall.data?.profiles ?? []"
          :rate-card="rateCard"
          :available="configCall.data?.available ?? 0"
          :currency="currency"
          :initial="initial"
        />
        <div class="flex items-center justify-between rounded-lg bg-surface-gray-1 px-3 py-2 text-p-sm">
          <span class="text-ink-gray-6">
            Now: {{ initial ? configSpecs(initial) : '—' }} ·
            {{ formatMoney(currentEstimate, currency) }}/mo
          </span>
          <span class="font-medium text-ink-gray-9">
            New: {{ formatMoney(newEstimate, currency) }}/mo
          </span>
        </div>
      </div>
    </template>
    <template #actions>
      <Button
        variant="solid"
        label="Resize"
        :loading="resizeCall.loading"
        :disabled="!changed"
        @click="confirm"
      />
    </template>
  </Dialog>
</template>
