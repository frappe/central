<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge, Button, FormControl, Tabs } from 'frappe-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import PlanCards from '@/components/servers/PlanCards.vue'
import { useRegions } from '@/composables/useRegions'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePlans } from '@/composables/usePlans'
import { planResources } from '@/lib/plans'
import type { Plan } from '@/types'

// New server. Region is the set of available Atlas Instances; the plan comes from
// the billing catalog, priced for the team's currency on that region and within
// its trust-tier headroom (usePlans). Create routes through central.api.servers
// .create_server — Atlas provisions raw resources, not plan names, so we pass the
// plan's bundled vcpus/memory/disk → the region's Atlas → a real VM (dev fake
// provider), mirrored back so it shows on the Servers list.
const router = useRouter()
const { regions, loading } = useRegions()
const { create, creating } = useServers()
const { canCreateServer } = useCapabilities()

const selectedRegion = ref<string | null>(null)
const name = ref('')
const selectedPlan = ref<string | null>(null)

// The menu arrives grouped by plan class (server-side: keys ordered, rows
// cheapest-first); `plans` is the flat view, `groups`/`classes` drive the tabs.
const { plans, groups, classes, loading: plansLoading } = usePlans(selectedRegion)

const selectedPlanObj = computed<Plan | null>(
  () => plans.value.find((p) => p.plan === selectedPlan.value) ?? null,
)

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

const canSubmit = computed(
  () =>
    canCreateServer.value &&
    !!selectedRegion.value &&
    !!selectedPlanObj.value &&
    name.value.trim().length > 0,
)

async function submit() {
  if (!canSubmit.value || !selectedRegion.value || !selectedPlanObj.value) return
  try {
    await create({
      region: selectedRegion.value,
      title: name.value.trim(),
      ...planResources(selectedPlanObj.value),
    })
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
        <div class="flex items-center gap-2">
          <span class="lucide-box size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Plan</h2>
        </div>

        <p v-if="!selectedRegion" class="text-p-sm text-ink-gray-5">
          Pick a region to see the plans available there.
        </p>
        <p v-else-if="plansLoading" class="text-p-sm text-ink-gray-5">Loading plans…</p>
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
          :loading="creating"
          :disabled="!canSubmit"
          @click="submit"
        />
      </div>
    </div>
  </div>
</template>
