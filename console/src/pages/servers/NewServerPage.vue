<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge, Button, FormControl, Tabs, useCall } from 'frappe-ui'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import { API, method } from '@/api/methods'
import { useRegions } from '@/composables/useRegions'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { usePlans } from '@/composables/usePlans'
import { money } from '@/lib/format'
import { planPrice, planResources } from '@/lib/plans'
import { configIncludes, estimateConfig, ramFor, rateCardComplete } from '@/lib/composed'
import { flagEmoji, hasMapCoords, regionLabel, type MapSpot } from '@/lib/serverMap'
import type { Region } from '@/types/Region'
import type { ComposedConfig, Plan, Profile } from '@/types/api'

// New server, the FC V2 way: a stepped form (name → provider → region → plan →
// version) beside the same world map the servers list uses — static here, framing
// the chosen provider's regions and taking clicks as region picks. Providers are
// derived from the real regions (Atlas Instances); plans come from the billing
// catalog (usePlans) priced within the team's headroom. A preset routes through
// create_server; a composed config through create_composed_server.
const router = useRouter()
const route = useRoute()
const { regions, loading } = useRegions()
const { create, createComposed, creating, creatingComposed } = useServers()
const { canCreateServer } = useCapabilities()
const { requireSetup } = useBillingSetup()

const name = ref('')
const selectedProvider = ref<string | null>(null)
const selectedRegion = ref<string | null>(null)
const hoverRegion = ref<string | null>(null)

// — Provider / region steps. A region with no provider files under "Other".
function providerOf(region: Region): string {
  return region.provider || 'Other'
}
const providers = computed(() => {
  const names = [...new Set(regions.value.map(providerOf))]
  return names.sort((a, b) => (a === 'Other' ? 1 : b === 'Other' ? -1 : a.localeCompare(b)))
})
const providerRegions = computed(() =>
  regions.value.filter((r) => providerOf(r) === selectedProvider.value),
)
const selectedRegionRow = computed(
  () => regions.value.find((r) => r.region === selectedRegion.value) ?? null,
)

function selectProvider(provider: string): void {
  if (provider === selectedProvider.value) return
  selectedProvider.value = provider
  // Land on the first region that's actually reachable, else the first one.
  const list = providerRegions.value
  selectedRegion.value = (list.find((r) => r.reachable) ?? list[0])?.region ?? null
}
function selectRegion(id: string): void {
  const region = regions.value.find((r) => r.region === id)
  if (!region) return
  selectedProvider.value = providerOf(region)
  selectedRegion.value = id
}

// Deep link from the servers map (+ spot → ?region=, or just ?provider=), once
// regions load; otherwise land on the first provider so the map has a frame.
// Each distinct ?region= applies exactly once — a data reload never stomps a
// pick the user made after landing, but a fresh in-app link still wins.
let appliedQueryRegion = ''
watch(
  [regions, () => route.query.region],
  ([list]) => {
    if (!list.length) return
    const wanted = typeof route.query.region === 'string' ? route.query.region : ''
    if (wanted && wanted !== appliedQueryRegion && list.some((r) => r.region === wanted)) {
      appliedQueryRegion = wanted
      return selectRegion(wanted)
    }
    if (selectedRegion.value) return
    const provider = typeof route.query.provider === 'string' ? route.query.provider : ''
    selectProvider(providers.value.includes(provider) ? provider : providers.value[0])
  },
  { immediate: true },
)

// The static map frames the chosen provider's placed regions; clicking a dot
// picks that region (0/0 coords = unplaced, listed in chips only).
const markers = computed<MapSpot[]>(() =>
  providerRegions.value.filter(hasMapCoords).map((r) => ({
    id: r.region,
    lat: r.latitude!,
    lng: r.longitude!,
    provider: r.provider || null,
    regionLabel: regionLabel(r),
    flag: flagEmoji(r.country_code),
  })),
)

// — Plan step (unchanged mechanics: presets + scoped Custom, tabs per profile).
// A preset name, or `custom:<profile>` for a designed config in that profile.
const selectedPlan = ref<string | null>(null)
const composedConfig = ref<ComposedConfig | null>(null)
const { plans, groups, classes, rateCard, profiles, available, currency, capacity, loading: plansLoading } =
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
// user can only ever drag into red.
const availableHeadroom = computed(() => available.value ?? 0)
const bracketExhausted = computed(
  () =>
    !!selectedRegion.value &&
    !plansLoading.value &&
    !plans.value.length &&
    canDesign.value &&
    cheapestDesignCost.value > availableHeadroom.value,
)

// The region itself is full: capacity gating is on and Atlas can't seat any new VM
// right now. A capacity dead-end, not a budget one — show a distinct message (and it
// takes priority, since there's nothing to provision here at any size).
const regionFull = computed(
  () => !!selectedRegion.value && !plansLoading.value && capacity.value.gated && !capacity.value.available,
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

// — Version step. Options come from the server (central.api.servers.frappe_versions)
//   so the form can't offer something create_server would refuse.
const versionsCall = useCall<string[]>({ url: method(API.frappeVersions) })
const VERSION_LABELS: Record<string, string> = {
  v15: 'Version 15 — stable, what most teams run',
  v16: 'Version 16 — latest features, newest apps',
  v14: 'Version 14 — older, for apps that need it',
  nightly: 'Nightly — develop branch, for testing only',
}
const version = ref('')
const versionOptions = computed(() =>
  (versionsCall.data ?? []).map((v) => ({ label: VERSION_LABELS[v] ?? v, value: v })),
)
watch(versionOptions, (options) => {
  if (!version.value && options.length) version.value = options[0].value
})

// — Submit. The header CTA carries the monthly price once a plan is picked.
const price = computed<string | null>(() => {
  if (isCustom.value && composedConfig.value && rateCardComplete(rateCard.value)) {
    const monthly = estimateConfig(composedConfig.value, rateCard.value)
    return `${money(monthly, currency.value ?? 'USD', { trimTrailingZeros: true })} / mo`
  }
  return selectedPlanObj.value ? planPrice(selectedPlanObj.value) : null
})
const ctaLabel = computed(() => (price.value ? `Create server — ${price.value}` : 'Create server'))

const submitting = computed(() => creating.value || creatingComposed.value)
const canSubmit = computed(() => {
  if (!canCreateServer.value || !selectedRegion.value || !name.value.trim()) return false
  if (regionFull.value) return false // the region can't seat a new server right now
  if (bracketExhausted.value) return false // nothing here fits the budget
  return isCustom.value ? !!composedConfig.value : !!selectedPlanObj.value
})

async function submit() {
  if (!canSubmit.value || !selectedRegion.value) return
  // A server bills the team, so it needs a billing profile first. If it's
  // incomplete, prompt (requireSetup toasts + flags the setup dialog) and send
  // them to Billing, where that dialog opens.
  if (!requireSetup()) {
    router.push({ name: 'Billing' })
    return
  }
  try {
    if (isCustom.value && composedConfig.value) {
      await createComposed({
        region: selectedRegion.value,
        title: name.value.trim(),
        includes: configIncludes(composedConfig.value),
        sub_category: composedConfig.value.sub_category,
        frappe_version: version.value || undefined,
      })
    } else if (selectedPlanObj.value) {
      await create({
        region: selectedRegion.value,
        title: name.value.trim(),
        plan: selectedPlanObj.value.plan,
        ...planResources(selectedPlanObj.value),
        frappe_version: version.value || undefined,
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
    <PageHeader title="New server">
      <template #actions>
        <Button label="Cancel" @click="router.push('/servers')" />
      </template>
    </PageHeader>

    <div class="flex min-h-0 flex-1 flex-col-reverse lg:flex-row">
      <!-- Stepped form (left) -->
      <div class="w-full overflow-y-auto p-6 lg:w-[40rem] lg:shrink-0">
        <p v-if="loading" class="text-p-sm text-ink-gray-5">Loading regions…</p>
        <p v-else-if="!regions.length" class="text-p-sm text-ink-gray-5">
          No active regions are available right now.
        </p>

        <div v-else>
          <!-- Step: name -->
          <div class="flex gap-4">
            <div class="flex flex-col items-center pt-1">
              <span class="size-2.5 shrink-0 rounded-full bg-[var(--ink-gray-9)]" />
              <span class="mt-1.5 w-px grow bg-[var(--outline-gray-2)]" />
            </div>
            <div class="min-w-0 flex-1 pb-8">
              <div class="text-sm font-medium text-ink-gray-7">Name the server</div>
              <FormControl v-model="name" type="text" placeholder="e.g. web-01" :maxlength="60" class="mt-2 max-w-xs" />
            </div>
          </div>

          <!-- Step: provider -->
          <div class="flex gap-4">
            <div class="flex flex-col items-center pt-1">
              <span class="size-2.5 shrink-0 rounded-full bg-[var(--ink-gray-9)]" />
              <span class="mt-1.5 w-px grow bg-[var(--outline-gray-2)]" />
            </div>
            <div class="min-w-0 flex-1 pb-8">
              <div class="text-sm font-medium text-ink-gray-7">Select a provider</div>
              <div class="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
                <button
                  v-for="p in providers"
                  :key="p"
                  class="flex w-full flex-col items-center gap-1.5 rounded-lg border p-2.5 transition-colors"
                  :class="
                    p === selectedProvider
                      ? 'border-outline-gray-4 ring-1 ring-outline-gray-4'
                      : 'border-outline-gray-2 hover:bg-surface-gray-1'
                  "
                  @click="selectProvider(p)"
                >
                  <ProviderAvatar :provider="p === 'Other' ? null : p" :size="32" />
                  <span class="truncate text-xs text-ink-gray-7">{{ p }}</span>
                </button>
              </div>
            </div>
          </div>

          <!-- Step: region -->
          <div class="flex gap-4">
            <div class="flex flex-col items-center pt-1">
              <span class="size-2.5 shrink-0 rounded-full bg-[var(--ink-gray-9)]" />
              <span class="mt-1.5 w-px grow bg-[var(--outline-gray-2)]" />
            </div>
            <div class="min-w-0 flex-1 pb-8">
              <div class="text-sm font-medium text-ink-gray-7">Select a region</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <Button
                  v-for="r in providerRegions"
                  :key="r.region"
                  size="sm"
                  variant="outline"
                  :class="r.region === selectedRegion ? '!border-outline-gray-5 font-medium !text-ink-gray-9' : ''"
                  @click="selectRegion(r.region)"
                  @mouseenter="hoverRegion = r.region"
                  @mouseleave="hoverRegion = null"
                >
                  <span class="mr-0.5 text-sm leading-none">{{ flagEmoji(r.country_code) }}</span>
                  {{ regionLabel(r) }}
                  <Badge v-if="!r.reachable" theme="gray" variant="subtle" label="Unreachable" class="ml-1" />
                </Button>
              </div>
            </div>
          </div>

          <!-- Step: plan (presets + a scoped Custom row, tabs by profile when needed) -->
          <div class="flex gap-4">
            <div class="flex flex-col items-center pt-1">
              <span class="size-2.5 shrink-0 rounded-full bg-[var(--ink-gray-9)]" />
              <span class="mt-1.5 w-px grow bg-[var(--outline-gray-2)]" />
            </div>
            <div class="min-w-0 flex-1 pb-8">
              <div class="mb-2 text-sm font-medium text-ink-gray-7">Select a plan</div>

              <p v-if="!selectedRegion" class="text-p-sm text-ink-gray-5">
                Pick a region to see the plans available there.
              </p>
              <p v-else-if="plansLoading" class="text-p-sm text-ink-gray-5">Loading plans…</p>

              <div
                v-else-if="regionFull"
                class="rounded-lg border border-outline-amber-1 bg-surface-amber-1 px-4 py-3"
              >
                <p class="text-p-sm font-medium text-ink-gray-8">This region is at capacity</p>
                <p class="mt-1 text-p-sm text-ink-gray-6">
                  {{ selectedRegion }} can't fit a new server right now. Try another region, or
                  check back shortly — capacity frees up as machines are removed.
                </p>
              </div>

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
                    :capacity="capacity"
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
                :capacity="capacity"
                v-model:selected-plan="selectedPlan"
                v-model:composed-config="composedConfig"
              />
            </div>
          </div>

          <!-- Step: version (last — no connector) -->
          <div class="flex gap-4">
            <div class="flex flex-col items-center pt-1">
              <span class="size-2.5 shrink-0 rounded-full bg-[var(--ink-gray-9)]" />
            </div>
            <div class="min-w-0 flex-1">
              <FormControl
                type="select"
                label="Frappe version"
                v-model="version"
                :options="versionOptions"
                class="max-w-xs"
              />
              <p v-if="selectedRegionRow" class="mt-4 flex items-center gap-1.5 text-p-xs text-ink-gray-5">
                <span class="lucide-map-pin size-3.5" />
                Runs in {{ regionLabel(selectedRegionRow) }} — this is where your data lives.
              </p>
              <Button
                class="mt-8"
                variant="solid"
                :label="ctaLabel"
                icon-left="lucide-plus"
                :loading="submitting"
                :disabled="!canSubmit"
                @click="submit"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Region map (right): the servers map in picker mode — no pan/zoom, it
           frames the provider's regions and takes clicks as picks. -->
      <div class="p-4 lg:flex-1">
        <div class="relative h-72 w-full overflow-hidden rounded-xl border border-outline-gray-2 lg:h-full">
          <ServerMap
            :interactive="false"
            :markers="markers"
            :selected-id="selectedRegion"
            :highlight-id="hoverRegion"
            @select="selectRegion"
          />
        </div>
      </div>
    </div>
  </div>
</template>
