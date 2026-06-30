<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge, Button, FormControl, Tabs } from 'frappe-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import PlanCards from '@/components/servers/PlanCards.vue'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { useRegions } from '@/composables/useRegions'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePlans } from '@/composables/usePlans'
import { planResources } from '@/lib/plans'
import { configIncludes, rateCardComplete } from '@/lib/composed'
import type { ComposedConfig, Plan } from '@/types/api'

// New server. Region is the set of available Atlas Instances; the plan comes from
// the billing catalog, priced for the team's currency on that region and within
// its trust-tier headroom (usePlans). A customer either picks a curated preset or
// designs their own config on a slider (#84). A preset routes through create_server
// (Atlas provisions raw resources); a composed config routes through
// create_composed_server, which also records the à-la-carte subscription (#80).
const router = useRouter()
const { regions, loading } = useRegions()
const { create, createComposed, creating, creatingComposed } = useServers()
const { canCreateServer } = useCapabilities()

const selectedRegion = ref<string | null>(null)
const name = ref('')
const selectedPlan = ref<string | null>(null)
const mode = ref<'preset' | 'design'>('preset')
const composedConfig = ref<ComposedConfig | null>(null)

// The menu arrives grouped by plan class (server-side: keys ordered, rows
// cheapest-first); `plans` is the flat view, `groups`/`classes` drive the tabs.
// `rateCard` + `profiles` + `available` feed the "design your own" slider.
const { plans, groups, classes, rateCard, profiles, available, currency, loading: plansLoading } =
  usePlans(selectedRegion)

// "Design your own" is offered only where the region prices every component.
const canDesign = computed(() => rateCardComplete(rateCard.value) && profiles.value.length > 0)

const selectedPlanObj = computed<Plan | null>(
  () => plans.value.find((p) => p.plan === selectedPlan.value) ?? null,
)

// The bundle-discount note: shown only while the designed shape sits exactly on a
// preset (a preset may price that shape below its component sum).
const matchingPreset = computed<Plan | null>(() => {
  const c = composedConfig.value
  if (!c) return null
  const qty = (p: Plan, type: string) => p.includes.find((i) => i.resource_type === type)?.quantity ?? 0
  return (
    plans.value.find(
      (p) => qty(p, 'Compute') === c.vcpus && qty(p, 'Memory') === c.memory_gb && qty(p, 'Disk') === c.disk_gb,
    ) ?? null
  )
})

// Bifurcate the menu by plan class, but only when the region actually offers more
// than one — a single-class region (e.g. just General) lists its plans flat.
const hasClassTabs = computed(() => classes.value.length > 1)
const classTabs = computed(() => classes.value.map((label) => ({ label })))
// Tabs select by index; reset to the first whenever the class list changes.
const activeTab = ref(0)

function plansInClass(planClass: string): Plan[] {
  return groups.value[planClass] ?? []
}

// Switching region re-prices the menu: drop a selection no longer offered, and
// point the class tabs back at the first class the new region has.
watch(plans, (rows) => {
  if (selectedPlan.value && !rows.some((p) => p.plan === selectedPlan.value)) {
    selectedPlan.value = null
  }
})
watch(classes, () => {
  activeTab.value = 0
})
// Switching to a region that can't price a custom config falls back to presets.
watch(canDesign, (ok) => {
  if (!ok && mode.value === 'design') mode.value = 'preset'
})

const submitting = computed(() => creating.value || creatingComposed.value)

const canSubmit = computed(() => {
  if (!canCreateServer.value || !selectedRegion.value || !name.value.trim()) return false
  return mode.value === 'design' ? !!composedConfig.value : !!selectedPlanObj.value
})

async function submit() {
  if (!canSubmit.value || !selectedRegion.value) return
  try {
    if (mode.value === 'design' && composedConfig.value) {
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
        <FormControl
          v-model="name"
          type="text"
          placeholder="e.g. web-01"
          :maxlength="60"
        />
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

      <!-- Plan -->
      <section class="space-y-3">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <span class="lucide-box size-4 text-ink-gray-6" aria-hidden="true" />
            <h2 class="text-base font-medium text-ink-gray-8">Plan</h2>
          </div>
          <!-- Preset vs design your own — only where the region prices a custom config. -->
          <div v-if="selectedRegion && canDesign" class="flex gap-1 rounded-lg bg-surface-gray-2 p-0.5">
            <button
              type="button"
              class="rounded-md px-3 py-1 text-p-sm transition-colors"
              :class="mode === 'preset' ? 'bg-surface-white text-ink-gray-9 shadow-sm' : 'text-ink-gray-6'"
              @click="mode = 'preset'"
            >
              Presets
            </button>
            <button
              type="button"
              class="rounded-md px-3 py-1 text-p-sm transition-colors"
              :class="mode === 'design' ? 'bg-surface-white text-ink-gray-9 shadow-sm' : 'text-ink-gray-6'"
              @click="mode = 'design'"
            >
              Design your own
            </button>
          </div>
        </div>

        <p v-if="!selectedRegion" class="text-p-sm text-ink-gray-5">
          Pick a region to see the plans available there.
        </p>
        <p v-else-if="plansLoading" class="text-p-sm text-ink-gray-5">Loading plans…</p>

        <!-- Design your own: the slider, fed by the rate card + profile bounds. -->
        <template v-else-if="mode === 'design'">
          <ConfigDesigner
            v-model="composedConfig"
            :profiles="profiles"
            :rate-card="rateCard"
            :available="available ?? 0"
            :currency="currency ?? 'USD'"
          />
          <p v-if="matchingPreset" class="text-p-xs text-ink-gray-5">
            The <span class="font-medium text-ink-gray-7">{{ matchingPreset.title }}</span> preset offers this
            exact shape — it may be cheaper than building it à la carte.
          </p>
        </template>

        <p v-else-if="!plans.length" class="text-p-sm text-ink-gray-5">
          No plans are available for this region within your current spending limit.
        </p>

        <!-- Multiple classes on this region: split them across tabs. -->
        <Tabs v-else-if="hasClassTabs" v-model="activeTab" :tabs="classTabs">
          <template #tab-panel="{ tab }">
            <PlanCards :plans="plansInClass(tab.label)" v-model="selectedPlan" class="pt-4" />
          </template>
        </Tabs>

        <!-- Single class: list the plans flat, unclassified. -->
        <PlanCards v-else :plans="plans" v-model="selectedPlan" />
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
