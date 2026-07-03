<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Checkbox, Dialog, LoadingIndicator, Tabs, useCall } from 'frappe-ui'
import MigrationMap from '@/components/servers/MigrationMap.vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import RegionPicker from '@/components/servers/RegionPicker.vue'
import ScheduleField from '@/components/servers/ScheduleField.vue'
import { API, method } from '@/api/methods'
import { usePlans } from '@/composables/usePlans'
import { useRegions } from '@/composables/useRegions'
import { useSession } from '@/composables/useSession'
import { configIncludes, configSpecs, estimateConfig, rateCardComplete } from '@/lib/composed'
import { money } from '@/lib/format'
import { specLine } from '@/lib/serverMap'
import { getErrorMessage, successToast } from '@/lib/toast'
import type { AssetRow } from '@/composables/useServers'
import type { ComposedConfig, Profile } from '@/types/api'
import type { Region } from '@/types/Region'

// The Change Plan flow (ported from the FC V2 mockup's central entry): one dialog
// for both operations on a server's contract. Staying in its region re-plans in
// place through the existing resize path; picking another region turns the footer
// into "Review migration" — a second step with the from→to map, an optional
// schedule, and the migrate call. Controlled by the page via v-model:server.
const props = defineProps<{ server: AssetRow | null }>()
const emit = defineEmits<{ 'update:server': [server: AssetRow | null]; changed: [] }>()

const { activeTeam } = useSession()
const activeTeamId = computed(() => activeTeam.value ?? '')
const { regions } = useRegions()

const step = ref<'choose' | 'review'>('choose')
const regionId = ref('')
const currentRegion = computed(() => props.server?.cluster ?? '')
const regionChanged = computed(() => !!regionId.value && regionId.value !== currentRegion.value)

// Region objects for the review map. The home region can be absent from the picker
// (list_instances hides Draining regions) — fall back to a name-only stub so the
// card still tells the story, just without a pin.
const regionOf = (id: string): Region =>
  regions.value.find((r) => r.region === id) ?? { region: id, status: 'Draining', reachable: 0 }
const fromRegion = computed(() => regionOf(currentRegion.value))
const toRegion = computed(() => regionOf(regionId.value))

const needsRestart = computed(() => props.server?.status === 'Running' || props.server?.status === 'Paused')
const resizeLabel = computed(() => (needsRestart.value ? 'Restart & resize' : 'Change plan'))

// The config running on this server (current shape + preset, and the subscription
// the change re-locks). Drives both the pre-selection and the headroom exclusion.
type ComposedConfigResponse = {
  resizable: boolean
  composed?: boolean
  subscription?: string
  sub_category?: string | null
  plan?: string | null
  vcpus?: number
  memory_gb?: number
  disk_gb?: number
}
const configCall = useCall<ComposedConfigResponse, { asset: string; team: string }>({
  url: method(API.composedConfig),
  params: () => ({ asset: props.server?.resource_id ?? '', team: activeTeamId.value }),
  immediate: false,
})
const subscription = computed(() => configCall.data?.subscription ?? null)

// The menu for the *picked* region (plans are priced and gated per region), with
// this server's own spend freed back into the headroom (exclude_subscription) —
// right for both paths, since a migration also replaces its subscription.
const planRegion = computed(() => regionId.value || currentRegion.value || null)
const { groups, classes, plans, rateCard, profiles, available, currency, loading: plansLoading } = usePlans(
  planRegion,
  subscription,
)

const open = computed({
  get: () => !!props.server,
  set: (v: boolean) => {
    // Don't let a stray close (Esc / backdrop) abandon an in-flight call.
    if (!v && !resizeCall.loading && !migrateCall.loading) emit('update:server', null)
  },
})

const dialogOptions = computed(() => ({
  title: step.value === 'review' ? 'Migrate your server' : 'Change plan',
  size: '2xl' as const,
}))

// A preset name, or `custom:<profile>` for a designed config in that profile — the
// exact shape PlanGroup speaks (matching the New Server flow).
const selectedPlan = ref<string | null>(null)
const composedConfig = ref<ComposedConfig | null>(null)
const isCustomSel = computed(() => (selectedPlan.value ?? '').startsWith('custom:'))
const resizable = computed(() => configCall.data?.resizable === true)

const canDesign = computed(() => rateCardComplete(rateCard.value) && profiles.value.length > 0)
function profileFor(cls: string): Profile | null {
  return profiles.value.find((p) => p.sub_category === cls) ?? null
}
function designableProfile(cls: string): Profile | null {
  return canDesign.value ? profileFor(cls) : null
}
const hasTabs = computed(() => classes.value.length > 1)
const classTabs = computed(() => classes.value.map((label) => ({ label })))
const activeTab = ref(0)
const soleClass = computed(() => classes.value[0] ?? 'General')
const flatPresets = computed(() => groups.value[soleClass.value] ?? [])
const flatProfile = computed<Profile | null>(() =>
  canDesign.value ? profileFor(soleClass.value) ?? profiles.value[0] ?? null : null,
)
const nothingToShow = computed(() => !hasTabs.value && !flatPresets.value.length && !flatProfile.value)

// The current shape, so the custom designer opens pre-filled on the running config.
const initial = computed<ComposedConfig | null>(() =>
  resizable.value
    ? {
        sub_category: configCall.data!.sub_category ?? profiles.value[0]?.sub_category ?? '',
        vcpus: configCall.data!.vcpus ?? 0,
        memory_gb: configCall.data!.memory_gb ?? 0,
        disk_gb: configCall.data!.disk_gb ?? 0,
      }
    : null,
)
// The custom designer seeds its profile from initial.sub_category, so only hand
// `initial` to the group whose profile actually matches — other tabs start fresh.
function initialFor(profile: Profile | null): ComposedConfig | null {
  return profile && initial.value?.sub_category === profile.sub_category ? initial.value : null
}

// Pre-select what the server runs today, once the config + menu have loaded: the
// current preset row, or the custom row in its profile pre-filled with its shape.
watch([() => configCall.data, plans], () => {
  if (!resizable.value || selectedPlan.value || !classes.value.length) return
  const cfg = configCall.data!
  if (cfg.composed) {
    const cls = cfg.sub_category ?? soleClass.value
    selectedPlan.value = `custom:${cls}`
    composedConfig.value = initial.value
    activeTab.value = Math.max(0, classes.value.indexOf(cls))
  } else if (cfg.plan && plans.value.some((p) => p.plan === cfg.plan)) {
    selectedPlan.value = cfg.plan
    const cls = plans.value.find((p) => p.plan === cfg.plan)?.sub_category ?? soleClass.value
    activeTab.value = Math.max(0, classes.value.indexOf(cls))
  }
})

// Reset when the dialog opens on a different server.
watch(
  () => props.server,
  (server) => {
    step.value = 'choose'
    regionId.value = server?.cluster ?? ''
    selectedPlan.value = null
    composedConfig.value = null
    activeTab.value = 0
    scheduled.value = false
    scheduleAt.value = ''
    if (server && activeTeamId.value) configCall.reload()
  },
)

// A same-region confirm is meaningful only when the selection differs from what's
// running. A migration doesn't need a different plan — moving is the change.
const changed = computed(() => {
  if (!selectedPlan.value) return false
  if (isCustomSel.value) {
    const c = composedConfig.value
    if (!c) return false
    if (!configCall.data?.composed) return true // preset → custom is always a change
    const i = initial.value
    return !i || c.vcpus !== i.vcpus || c.disk_gb !== i.disk_gb || c.sub_category !== i.sub_category
  }
  return selectedPlan.value !== configCall.data?.plan
})
const selectionValid = computed(
  () => !!selectedPlan.value && (!isCustomSel.value || !!composedConfig.value),
)

// The review card's cost pill: the picked preset's regional rate, or the composed
// config summed from the rate card.
const newRate = computed<number | null>(() => {
  if (isCustomSel.value)
    return composedConfig.value ? estimateConfig(composedConfig.value, rateCard.value) : null
  const plan = plans.value.find((p) => p.plan === selectedPlan.value)
  return plan?.rate ?? null
})
const costLabel = computed(() =>
  newRate.value != null ? money(newRate.value, currency.value ?? 'USD', { trimTrailingZeros: true }) : '',
)
const fromPlanLabel = computed(() => (props.server ? specLine(props.server) : ''))
const toPlanLabel = computed(() => {
  if (isCustomSel.value) return composedConfig.value ? `Custom · ${configSpecs(composedConfig.value)}` : 'Custom'
  return plans.value.find((p) => p.plan === selectedPlan.value)?.title ?? ''
})

// --- step 2: schedule + migrate -------------------------------------------

const scheduled = ref(false)
const scheduleAt = ref('')
watch(scheduled, (on) => {
  if (!on) scheduleAt.value = ''
})

const resizeCall = useCall<
  { subscription: string; queued: boolean; resized: boolean },
  Record<string, unknown>
>({
  url: method(API.resizeServer),
  method: 'POST',
  immediate: false,
})
const migrateCall = useCall<{ migration: string; status: string }, Record<string, unknown>>({
  url: method(API.migrateServer),
  method: 'POST',
  immediate: false,
})

// A failed call keeps the dialog open with the reason shown, instead of silently
// dropping back. Cleared when the selection changes so a fresh attempt starts clean.
const actionError = computed(() => {
  if (resizeCall.error) return getErrorMessage(resizeCall.error, "Couldn't resize the server.")
  if (migrateCall.error) return getErrorMessage(migrateCall.error, "Couldn't start the migration.")
  return ''
})
watch([selectedPlan, composedConfig, regionId], () => {
  resizeCall.reset()
  migrateCall.reset()
})

async function confirmResize() {
  const sub = subscription.value
  if (!sub || !changed.value) return
  const payload =
    isCustomSel.value && composedConfig.value
      ? {
          subscription: sub,
          includes: configIncludes(composedConfig.value),
          sub_category: composedConfig.value.sub_category,
        }
      : { subscription: sub, plan: selectedPlan.value }
  await resizeCall.submit(payload)
  if (!resizeCall.error) {
    // The reshape runs in the background — the server shows "Resizing" in the list
    // and comes back on its own — so confirm and close instead of holding the dialog.
    const name = props.server?.title || props.server?.resource_id
    successToast(
      resizeCall.data?.queued
        ? `Resizing ${name} — the server list shows its progress.`
        : `Resized ${name}.`,
    )
    emit('changed')
    open.value = false
  }
}

async function confirmMigrate() {
  if (!props.server || !selectionValid.value) return
  const target =
    isCustomSel.value && composedConfig.value
      ? {
          includes: configIncludes(composedConfig.value),
          sub_category: composedConfig.value.sub_category,
        }
      : { plan: selectedPlan.value }
  await migrateCall.submit({
    team: activeTeamId.value,
    resource_id: props.server.resource_id,
    region: regionId.value,
    ...(scheduled.value && scheduleAt.value ? { scheduled_at: scheduleAt.value } : {}),
    ...target,
  })
  if (migrateCall.error) {
    step.value = 'choose' // the error strip lives on step 1, next to what caused it
    return
  }
  const name = props.server.title || props.server.resource_id
  if (scheduled.value && scheduleAt.value) {
    successToast(`Migration of ${name} scheduled for ${new Date(scheduleAt.value.replace(' ', 'T')).toLocaleString()}.`)
  } else {
    successToast(`Migrating ${name} — the server list shows its progress.`)
  }
  emit('changed')
  open.value = false
}
</script>

<template>
  <Dialog v-model="open" :options="dialogOptions">
    <template #body-content>
      <!-- Both calls return fast (the slow work runs in background jobs), but hold a
           clear in-progress state so a double-click can't fire twice. -->
      <div
        v-if="resizeCall.loading || migrateCall.loading"
        class="flex flex-col items-center gap-3 py-10 text-center"
      >
        <LoadingIndicator class="h-6 w-6 text-ink-gray-5" />
        <p class="text-p-base font-medium text-ink-gray-8">
          {{ migrateCall.loading ? 'Starting migration…' : 'Starting resize…' }}
        </p>
      </div>
      <p v-else-if="configCall.loading" class="text-p-sm text-ink-gray-5">Loading…</p>
      <p v-else-if="!resizable" class="text-p-sm text-ink-gray-5">
        This server's plan can't be changed right now.
      </p>

      <!-- Step 1 — pick a region + plan -->
      <div v-else-if="step === 'choose'" class="space-y-4">
        <div
          v-if="actionError"
          class="rounded-lg border border-outline-red-2 bg-surface-red-1 px-3 py-2.5 text-p-sm text-ink-red-4"
        >
          {{ actionError }}
        </div>

        <RegionPicker v-model="regionId" :regions="regions" :current-region="currentRegion" />

        <div
          v-if="regionChanged"
          class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-3 py-2.5 text-p-sm text-ink-gray-6"
        >
          Moving to another region migrates the server — you'll review it before anything happens.
        </div>
        <div
          v-else-if="needsRestart"
          class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-3 py-2.5 text-p-sm text-ink-gray-6"
        >
          Your server will be briefly stopped to apply the new size, then started again automatically.
        </div>

        <p v-if="plansLoading" class="text-p-sm text-ink-gray-5">Loading plans…</p>
        <p v-else-if="nothingToShow" class="text-p-sm text-ink-gray-5">
          No plans are available in this region for your team.
        </p>
        <template v-else>
          <Tabs v-if="hasTabs" v-model="activeTab" :tabs="classTabs">
            <template #tab-panel="{ tab }">
              <PlanGroup
                class="pt-4"
                :presets="groups[tab.label] ?? []"
                :profile="designableProfile(tab.label)"
                :rate-card="rateCard"
                :available="available ?? 0"
                :currency="currency ?? 'USD'"
                :initial="initialFor(designableProfile(tab.label))"
                v-model:selected-plan="selectedPlan"
                v-model:composed-config="composedConfig"
              />
            </template>
          </Tabs>
          <PlanGroup
            v-else
            :presets="flatPresets"
            :profile="flatProfile"
            :rate-card="rateCard"
            :available="available ?? 0"
            :currency="currency ?? 'USD'"
            :initial="initialFor(flatProfile)"
            v-model:selected-plan="selectedPlan"
            v-model:composed-config="composedConfig"
          />
        </template>
      </div>

      <!-- Step 2 — review the migration -->
      <div v-else class="space-y-4">
        <p class="text-p-sm text-ink-gray-5">
          Your server will be briefly unavailable during the migration.
        </p>
        <MigrationMap
          :from="fromRegion"
          :to="toRegion"
          :from-plan="fromPlanLabel"
          :to-plan="toPlanLabel"
          :cost="costLabel"
        />
        <div class="flex items-start gap-3">
          <Checkbox v-model="scheduled" label="Schedule for later" />
          <ScheduleField v-if="scheduled" v-model="scheduleAt" class="ml-auto items-end" />
        </div>
      </div>
    </template>

    <template #actions>
      <div
        v-if="resizable && !resizeCall.loading && !migrateCall.loading"
        class="flex items-center justify-end gap-2"
      >
        <template v-if="step === 'choose'">
          <Button label="Cancel" @click="open = false" />
          <Button
            v-if="regionChanged"
            variant="solid"
            label="Review migration"
            icon-right="lucide-arrow-right"
            :disabled="!selectionValid"
            @click="step = 'review'"
          />
          <Button
            v-else
            variant="solid"
            :label="resizeLabel"
            :disabled="!changed"
            @click="confirmResize"
          />
        </template>
        <template v-else>
          <Button icon-left="lucide-arrow-left" label="Back" @click="step = 'choose'" />
          <Button
            variant="solid"
            :label="scheduled ? 'Schedule migration' : 'Migrate'"
            :disabled="scheduled && !scheduleAt"
            @click="confirmMigrate"
          />
        </template>
      </div>
    </template>
  </Dialog>
</template>
