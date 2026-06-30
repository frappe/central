<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge, Button, FormControl } from 'frappe-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { useRegions } from '@/composables/useRegions'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePlans } from '@/composables/usePlans'
import { planResources, planSpecs, planPrice, formatMoney } from '@/lib/plans'
import { configIncludes, configSpecs, estimateConfig, rateCardComplete } from '@/lib/composed'
import type { ComposedConfig, Plan } from '@/types/api'

// New server. Region is the set of available Atlas Instances; the plan comes from
// the billing catalog, priced for the team's currency on that region and within its
// trust-tier headroom (usePlans). The picker is one radio list: the curated presets,
// plus a "Custom" row that expands into a slider to design your own config (#84). A
// preset routes through create_server (Atlas provisions raw resources); a composed
// config routes through create_composed_server, which records the subscription (#80).
const CUSTOM = '__custom__'

const router = useRouter()
const { regions, loading } = useRegions()
const { create, createComposed, creating, creatingComposed } = useServers()
const { canCreateServer } = useCapabilities()

const selectedRegion = ref<string | null>(null)
const name = ref('')
const selectedPlan = ref<string | null>(null)
const composedConfig = ref<ComposedConfig | null>(null)

// `plans` is the flat, cheapest-first preset list; `rateCard` + `profiles` +
// `available` feed the Custom slider.
const { plans, rateCard, profiles, available, currency, loading: plansLoading } = usePlans(selectedRegion)

// "Custom" is offered only where the region prices every component.
const canDesign = computed(() => rateCardComplete(rateCard.value) && profiles.value.length > 0)
const isCustom = computed(() => selectedPlan.value === CUSTOM)

const selectedPlanObj = computed<Plan | null>(
  () => plans.value.find((p) => p.plan === selectedPlan.value) ?? null,
)

// Live spec + price for the Custom row, shown inline like a preset.
const customEstimate = computed<number | null>(() =>
  composedConfig.value ? estimateConfig(composedConfig.value, rateCard.value) : null,
)
const customSpec = computed<string>(() => (composedConfig.value ? configSpecs(composedConfig.value) : ''))
const customPrice = computed<string>(() =>
  customEstimate.value !== null ? `${formatMoney(customEstimate.value, currency.value ?? 'USD')} / mo` : '',
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

// Switching region re-prices the menu: drop a now-unoffered preset selection, and
// drop a Custom selection if the new region can't price one.
watch([plans, canDesign], () => {
  if (selectedPlan.value === CUSTOM) {
    if (!canDesign.value) selectedPlan.value = null
  } else if (selectedPlan.value && !plans.value.some((p) => p.plan === selectedPlan.value)) {
    selectedPlan.value = null
  }
})

const submitting = computed(() => creating.value || creatingComposed.value)

const canSubmit = computed(() => {
  if (!canCreateServer.value || !selectedRegion.value || !name.value.trim()) return false
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

      <!-- Plan: one radio list of presets + a Custom row that expands into the slider. -->
      <section class="space-y-3">
        <div class="flex items-center gap-2">
          <span class="lucide-box size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Select a plan</h2>
        </div>

        <p v-if="!selectedRegion" class="text-p-sm text-ink-gray-5">
          Pick a region to see the plans available there.
        </p>
        <p v-else-if="plansLoading" class="text-p-sm text-ink-gray-5">Loading plans…</p>
        <p v-else-if="!plans.length && !canDesign" class="text-p-sm text-ink-gray-5">
          No plans are available for this region within your current spending limit.
        </p>

        <div v-else class="space-y-3">
          <!-- Presets -->
          <label
            v-for="plan in plans"
            :key="plan.plan"
            class="flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition-colors"
            :class="
              selectedPlan === plan.plan
                ? 'border-outline-gray-4'
                : 'border-outline-gray-2 hover:border-outline-gray-3'
            "
          >
            <input v-model="selectedPlan" type="radio" :value="plan.plan" class="accent-ink-gray-9" />
            <span class="font-medium text-ink-gray-9">{{ plan.title }}</span>
            <span class="text-p-sm text-ink-gray-5">{{ planSpecs(plan) }}</span>
            <span class="ml-auto font-medium text-ink-gray-9">{{ planPrice(plan) }}</span>
          </label>

          <!-- Custom: a radio row that expands into the design slider. -->
          <div
            v-if="canDesign"
            class="rounded-lg border transition-colors"
            :class="isCustom ? 'border-outline-gray-4' : 'border-outline-gray-2 hover:border-outline-gray-3'"
          >
            <label class="flex cursor-pointer items-center gap-3 px-4 py-3">
              <input v-model="selectedPlan" type="radio" :value="CUSTOM" class="accent-ink-gray-9" />
              <span class="font-medium text-ink-gray-9">Custom</span>
              <span class="lucide-sliders-horizontal size-4 text-ink-gray-5" aria-hidden="true" />
              <span v-if="isCustom && customSpec" class="text-p-sm text-ink-gray-5">{{ customSpec }}</span>
              <span class="ml-auto font-medium text-ink-gray-9">{{ isCustom ? customPrice : 'Design your own' }}</span>
            </label>

            <!-- Smooth expand: animate grid rows from 0fr → 1fr (CSS only). -->
            <div
              class="grid transition-[grid-template-rows] duration-200 ease-out"
              :class="isCustom ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
            >
              <div class="overflow-hidden">
                <div class="border-t border-outline-gray-2 px-4 py-4">
                  <ConfigDesigner
                    v-model="composedConfig"
                    :profiles="profiles"
                    :rate-card="rateCard"
                    :available="available ?? 0"
                  />
                  <p v-if="matchingPreset" class="mt-3 text-p-xs text-ink-gray-5">
                    The <span class="font-medium text-ink-gray-7">{{ matchingPreset.title }}</span> preset offers
                    this exact shape — it may be cheaper than building it à la carte.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
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
