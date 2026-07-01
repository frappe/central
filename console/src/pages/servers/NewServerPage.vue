<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge, Button, FormControl, Tabs } from 'frappe-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import { useRegions } from '@/composables/useRegions'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePlans } from '@/composables/usePlans'
import { planResources } from '@/lib/plans'
import { configIncludes, estimateConfig, ramFor, rateCardComplete } from '@/lib/composed'
import type { ComposedConfig, Plan, Profile } from '@/types/api'

// New server. Region is the set of available Atlas Instances; plans come from the
// billing catalog (usePlans), priced for the team's currency on that region and
// within its headroom. The picker mirrors the catalog's shape: when a region's
// presets span several optimisation profiles it splits into tabs, each listing that
// profile's presets + a Custom row scoped to it; a region with one (or no)
// sub-classification stays a flat list with a simple Custom (#84). A preset routes
// through create_server; a composed config through create_composed_server (#80).
const router = useRouter()
const { regions, loading } = useRegions()
const { create, createComposed, creating, creatingComposed } = useServers()
const { canCreateServer } = useCapabilities()

const selectedRegion = ref<string | null>(null)
const name = ref('')
// A preset name, or `custom:<profile>` for a designed config in that profile.
const selectedPlan = ref<string | null>(null)
const composedConfig = ref<ComposedConfig | null>(null)

const { plans, groups, classes, rateCard, profiles, available, currency, loading: plansLoading } =
  usePlans(selectedRegion)

const canDesign = computed(() => rateCardComplete(rateCard.value) && profiles.value.length > 0)
const isCustom = computed(() => (selectedPlan.value ?? '').startsWith('custom:'))
const selectedPlanObj = computed<Plan | null>(
  () => plans.value.find((p) => p.plan === selectedPlan.value) ?? null,
)

function profileFor(cls: string): Profile | null {
  return profiles.value.find((p) => p.sub_category === cls) ?? null
}

// Tabs when the region's presets span more than one profile; flat otherwise.
const hasTabs = computed(() => classes.value.length > 1)
const classTabs = computed(() => classes.value.map((label) => ({ label })))
const activeTab = ref(0)

// Flat layout: the sole preset class, or General when a region offers only a designer.
const soleClass = computed(() => classes.value[0] ?? 'General')
const flatPresets = computed<Plan[]>(() => groups.value[soleClass.value] ?? [])
// Custom is only offered where the region actually prices every component (else the
// estimate would be a $0 dead-end) — so a profile is "designable" only when canDesign.
const flatProfile = computed<Profile | null>(() =>
  canDesign.value
    ? profileFor(soleClass.value) ??
      profiles.value.find((p) => p.sub_category === 'General') ??
      profiles.value[0] ??
      null
    : null,
)
function designableProfile(cls: string): Profile | null {
  return canDesign.value ? profileFor(cls) : null
}
const nothingToShow = computed(() => !hasTabs.value && !flatPresets.value.length && !flatProfile.value)

// The cheapest config a profile can be dragged to: its smallest vCPU rung (with the
// RAM that ratio implies) on its smallest disk rung.
function floorConfigCost(profile: Profile): number {
  const vcpus = [...(profile.vcpu_steps ?? [])].sort((a, b) => a - b)[0] ?? 0
  const diskGb = [...(profile.disk_steps ?? [])].sort((a, b) => a - b)[0] ?? 0
  return estimateConfig(
    { sub_category: profile.sub_category, vcpus, memory_gb: ramFor(vcpus, profile), disk_gb: diskGb },
    rateCard.value,
  )
}
const cheapestDesignCost = computed<number>(() =>
  canDesign.value && profiles.value.length
    ? Math.min(...profiles.value.map(floorConfigCost))
    : Infinity,
)

// Tier bracket exhausted: a region is picked, no preset fits the remaining headroom
// (the menu is already headroom-filtered server-side), and even the smallest custom
// config is over the limit. Show a dead-end message rather than a Custom slider the
// user can only ever drag into red — offering a config they can't create is worse UX
// than telling them the limit is spent.
const availableHeadroom = computed(() => available.value ?? 0)
const bracketExhausted = computed(
  () =>
    !!selectedRegion.value &&
    !plansLoading.value &&
    !plans.value.length &&
    canDesign.value &&
    cheapestDesignCost.value > availableHeadroom.value,
)

// Switching region re-prices the menu: reset the tab and drop a selection the new
// region no longer offers (a preset that's gone, or a custom profile it lacks).
watch(classes, () => {
  activeTab.value = 0
})
watch([plans, canDesign], () => {
  const sel = selectedPlan.value
  if (!sel) return
  if (sel.startsWith('custom:')) {
    if (!profileFor(sel.slice('custom:'.length))) selectedPlan.value = null
  } else if (!plans.value.some((p) => p.plan === sel)) {
    selectedPlan.value = null
  }
})

const submitting = computed(() => creating.value || creatingComposed.value)
const canSubmit = computed(() => {
  if (!canCreateServer.value || !selectedRegion.value || !name.value.trim()) return false
  if (bracketExhausted.value) return false // nothing here fits the budget
  return isCustom.value ? !!composedConfig.value : !!selectedPlanObj.value
})

async function submit() {
  if (!canSubmit.value || !selectedRegion.value) return
  try {
    if (isCustom.value && composedConfig.value) {
      await createComposed({
        region: selectedRegion.value,
        title: name.value.trim(),
        includes: configIncludes(composedConfig.value),
        sub_category: composedConfig.value.sub_category,
      })
    } else if (selectedPlanObj.value) {
      await create({
        region: selectedRegion.value,
        title: name.value.trim(),
        plan: selectedPlanObj.value.plan,
        ...planResources(selectedPlanObj.value),
      })
    }
    router.push('/servers')
  } catch {
    // create() already surfaced the error; stay on the form.
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="New server" subtitle="Pick where it lives and how big it is.">
      <template #actions>
        <Button label="Back" icon-left="lucide-arrow-left" @click="router.push('/servers')" />
      </template>
    </PageHeader>

    <div class="page-body max-w-[760px] space-y-8 py-6">
      <!-- Name -->
      <section class="space-y-3">
        <div class="flex items-center gap-2">
          <span class="lucide-tag size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Name</h2>
        </div>
        <FormControl v-model="name" type="text" placeholder="e.g. web-01" :maxlength="60" />
      </section>

      <!-- Region -->
      <section class="space-y-3">
        <div class="flex items-center gap-2">
          <span class="lucide-globe size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Region</h2>
        </div>

        <p v-if="loading" class="text-p-sm text-ink-gray-5">Loading regions…</p>
        <p v-else-if="!regions.length" class="text-p-sm text-ink-gray-5">
          No active regions are available right now.
        </p>

        <div v-else class="grid gap-3 sm:grid-cols-2">
          <button
            v-for="region in regions"
            :key="region.region"
            type="button"
            class="flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-colors"
            :class="
              selectedRegion === region.region
                ? 'border-outline-gray-4 bg-surface-gray-2'
                : 'border-outline-gray-2 hover:border-outline-gray-3'
            "
            @click="selectedRegion = region.region"
          >
            <div class="min-w-0">
              <p class="truncate font-medium text-ink-gray-9">{{ region.region }}</p>
              <p class="text-p-sm text-ink-gray-5">Atlas region</p>
            </div>
            <Badge
              :theme="region.reachable ? 'green' : 'gray'"
              :label="region.reachable ? 'Reachable' : 'Unreachable'"
              variant="subtle"
            />
          </button>
        </div>
      </section>

      <!-- Plan: presets + a scoped Custom row, split into tabs by profile when needed. -->
      <section class="space-y-3">
        <div class="flex items-center gap-2">
          <span class="lucide-box size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Select a plan</h2>
        </div>

        <p v-if="!selectedRegion" class="text-p-sm text-ink-gray-5">
          Pick a region to see the plans available there.
        </p>
        <p v-else-if="plansLoading" class="text-p-sm text-ink-gray-5">Loading plans…</p>

        <div
          v-else-if="bracketExhausted"
          class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-4 py-3"
        >
          <p class="text-p-sm font-medium text-ink-gray-8">You've reached your spending limit</p>
          <p class="mt-1 text-p-sm text-ink-gray-5">
            No plans — preset or custom — fit your remaining headroom in this region. Remove a
            server to free some up, or contact support to raise your limit.
          </p>
        </div>

        <p v-else-if="nothingToShow" class="text-p-sm text-ink-gray-5">
          No plans are available for this region within your current spending limit.
        </p>

        <Tabs v-else-if="hasTabs" v-model="activeTab" :tabs="classTabs">
          <template #tab-panel="{ tab }">
            <PlanGroup
              class="pt-4"
              :presets="groups[tab.label] ?? []"
              :profile="designableProfile(tab.label)"
              :rate-card="rateCard"
              :available="available ?? 0"
              :currency="currency ?? 'USD'"
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
          v-model:selected-plan="selectedPlan"
          v-model:composed-config="composedConfig"
        />
      </section>

      <!-- Submit -->
      <div class="flex items-center justify-end gap-3 border-t border-outline-gray-1 pt-5">
        <Button label="Cancel" @click="router.push('/servers')" />
        <Button
          variant="solid"
          label="Create server"
          icon-left="lucide-plus"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="submit"
        />
      </div>
    </div>
  </div>
</template>
