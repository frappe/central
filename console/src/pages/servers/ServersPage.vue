<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Servers">
      <template #actions>
        <Button label="Refresh" icon-left="lucide-refresh-cw" :loading="refreshing" @click="doRefresh" />
        <Button
          v-if="canCreateServer"
          variant="solid"
          label="New server"
          icon-left="lucide-plus"
          @click="$router.push('/servers/new')"
        />
      </template>
    </PageHeader>

    <!-- The map is the page. Everything else floats above it. `isolate` keeps
         the overlays' z-indexes from leaking above body-portaled menus. -->
    <div class="relative isolate flex-1 overflow-hidden">
      <ServerMap
        ref="mapRef"
        class="absolute inset-0"
        :pins="pins"
        :spots="spots"
        :highlight-id="hoverId"
        :allow-create="canCreateServer"
        @open="onOpen"
        @new-server="goNewServer"
        @cluster-open="onClusterOpen"
      >
        <template #card-actions="{ server }">
          <ServerRowActions
            :server="server"
            :can-open="canOpenServer"
            :can-power="canPowerServer"
            :can-terminate="canTerminateServer"
            :busy="busy === server.resource_id"
            :opening="opening === server.resource_id"
            :scheduled-migration="!!scheduledFor(server.resource_id)"
            @open="open"
            @start="doStart"
            @stop="doStop"
            @change-plan="pendingChange = $event"
            @cancel-migration="doCancelMigration"
            @terminate="pendingTerminate = $event"
          />
        </template>
      </ServerMap>

      <!-- Mirror-health strips (top center): reachability first, then load errors. -->
      <div class="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4">
        <p
          v-if="stale.length"
          class="pointer-events-auto rounded-md bg-surface-amber-1 px-3 py-2 text-p-sm text-ink-amber-3 shadow-sm"
        >
          Showing last-known data — couldn't reach: {{ stale.join(', ') }}
        </p>
        <p
          v-else-if="error && rows.length"
          class="pointer-events-auto rounded-md bg-surface-red-1 px-3 py-2 text-p-sm text-ink-red-3 shadow-sm"
        >
          {{ error }}
          <button class="ml-1 font-medium underline" @click="reloadAll">Retry</button>
        </p>
      </div>

      <!-- Filters (top right) -->
      <div class="absolute right-4 top-4 flex items-center gap-2">
        <Dropdown :options="statusMenu" placement="right">
          <button class="sp-pill">
            <span class="size-2 rounded-full transition-colors" :style="{ background: statusDot }" />
            {{ statusLabelText }}
            <span class="lucide-chevron-down size-3.5 text-ink-gray-5" />
          </button>
        </Dropdown>
        <!-- Region = provider → region, drilled through a nested menu. -->
        <Dropdown :options="regionMenu" placement="right">
          <button class="sp-pill">
            {{ regionLabelText }}
            <span class="lucide-chevron-down size-3.5 text-ink-gray-5" />
          </button>
        </Dropdown>
      </div>

      <!-- Your servers (top left): a floating card — the pill IS the panel,
           collapsed. Opening expands it in place; content crossfades. -->
      <section
        class="sp-float absolute left-4 top-4 z-30 overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-elevation-1"
        :class="panelOpen && 'sp-float-open'"
      >
        <button class="sp-float-pill" :inert="panelOpen" @click="panelOpen = true">
          <span class="truncate">{{ pillLabel }}</span>
          <span class="lucide-maximize-2 size-3.5 shrink-0 text-ink-gray-6" />
        </button>

        <div
          class="sp-float-panel flex h-full min-h-0 flex-col"
          :inert="!panelOpen"
          :aria-hidden="!panelOpen"
        >
          <div class="flex shrink-0 items-center justify-between gap-2 px-4 pb-2 pt-4">
            <h2 class="text-lg font-semibold text-ink-gray-9">Your servers ({{ filtered.length }})</h2>
            <Button variant="ghost" icon="lucide-minimize-2" aria-label="Collapse list" @click="panelOpen = false" />
          </div>
          <div class="shrink-0 px-4 pb-3">
            <FormControl v-model="q" type="text" placeholder="Search" autocomplete="off" class="[&_input]:w-full">
              <template #prefix><span class="lucide-search size-4 text-ink-gray-5" /></template>
            </FormControl>
          </div>

          <!-- Set by clicking a cluster on the map — the rows narrow to that spot. -->
          <div v-if="locationFilter" class="flex shrink-0 items-center justify-between gap-3 px-4 pb-2.5">
            <span class="min-w-0 truncate text-sm text-ink-gray-5">
              Filtering for <span class="font-medium text-ink-gray-8">{{ locationFilter.label }}</span>
            </span>
            <button
              class="flex shrink-0 items-center gap-1.5 text-sm text-ink-gray-6 transition-colors hover:text-ink-gray-8"
              @click="locationFilter = null"
            >
              <span class="lucide-filter size-3.5" />
              Clear
            </button>
          </div>

          <div class="min-h-0 flex-1 divide-y divide-outline-alpha-gray-1 overflow-y-auto border-t border-outline-alpha-gray-1 px-2 pb-2">
            <div
              v-for="(row, i) in panelRows"
              :key="row.id"
              class="sp-row group flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-surface-gray-2"
              :style="{ animationDelay: `${Math.min(i * 25, 200)}ms` }"
              @click="focusRow(row)"
              @mouseenter="hoverId = row.id"
              @mouseleave="hoverId = null"
            >
              <span class="relative shrink-0">
                <ProviderAvatar :provider="row.provider" :size="32" />
                <span
                  class="absolute -bottom-px -right-px size-2.5 rounded-full border-2 border-[var(--surface-elevation-1)]"
                  :style="{ background: row.visual.dot }"
                />
              </span>
              <span class="min-w-0 flex-1">
                <span class="flex items-center gap-1.5">
                  <span class="truncate text-sm font-medium text-ink-gray-9">{{ row.name }}</span>
                  <Badge
                    v-if="row.visual.key !== 'active'"
                    :label="row.visual.label"
                    :theme="row.visual.badgeTheme"
                    variant="subtle"
                    size="sm"
                  />
                  <Badge
                    v-if="scheduledFor(row.asset.resource_id)"
                    label="Migration scheduled"
                    theme="blue"
                    variant="subtle"
                    size="sm"
                  />
                </span>
                <span class="block truncate text-sm text-ink-gray-5">{{ row.specs || row.regionLabel }}</span>
              </span>
              <span @click.stop>
                <ServerRowActions
                  :server="row.asset"
                  :can-open="canOpenServer"
                  :can-power="canPowerServer"
                  :can-terminate="canTerminateServer"
                  :busy="busy === row.id"
                  :opening="opening === row.id"
                  :scheduled-migration="!!scheduledFor(row.asset.resource_id)"
                  @open="open"
                  @start="doStart"
                  @stop="doStop"
                  @change-plan="pendingChange = $event"
                  @cancel-migration="doCancelMigration"
                  @terminate="pendingTerminate = $event"
                />
              </span>
            </div>

            <div v-if="!panelRows.length" class="m-4 flex flex-col items-center gap-1 py-8 text-center">
              <span :class="rows.length ? 'lucide-search' : 'lucide-server'" class="mb-2 size-6 text-ink-gray-4" />
              <p class="text-base font-medium text-ink-gray-8">{{ rows.length ? 'No servers match' : 'No servers yet' }}</p>
              <p class="text-sm text-ink-gray-5">
                {{ rows.length ? 'Try a different search or clear the filters.' : 'Create your first server to host your sites.' }}
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- Initial load / hard failure / first run — centered over the map -->
      <div
        v-if="loading && !rows.length"
        class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center"
      >
        <Spinner class="size-5 text-ink-gray-5" />
      </div>
      <div
        v-else-if="error && !rows.length"
        class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center px-4"
      >
        <div class="pointer-events-auto flex w-[26rem] max-w-full flex-col items-center gap-1 rounded-xl border border-outline-gray-1 bg-surface-elevation-1 p-6 text-center shadow-lg">
          <span class="lucide-circle-alert mb-2 size-6 text-ink-red-5" />
          <p class="text-base font-medium text-ink-gray-8">Couldn't load your servers</p>
          <p class="text-sm text-ink-gray-5">{{ error }}</p>
          <Button class="mt-3" label="Retry" @click="reloadAll" />
        </div>
      </div>
      <div
        v-else-if="!loading && !rows.length"
        class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center px-4"
      >
        <div class="pointer-events-auto flex w-[26rem] max-w-full flex-col items-center gap-1 rounded-xl border border-outline-gray-1 bg-surface-elevation-1 p-6 text-center shadow-lg">
          <span class="lucide-server mb-2 size-6 text-ink-gray-4" />
          <p class="text-base font-medium text-ink-gray-8">No servers yet</p>
          <p class="text-sm text-ink-gray-5">
            {{ canCreateServer ? 'Create your first server to host your sites — or pick a spot on the map.' : 'Servers your team creates will show up here.' }}
          </p>
          <Button
            v-if="canCreateServer"
            class="mt-3"
            variant="solid"
            label="New server"
            icon-left="lucide-plus"
            @click="$router.push('/servers/new')"
          />
        </div>
      </div>
    </div>

    <TerminateDialog
      v-model:server="pendingTerminate"
      :loading="busy === pendingTerminate?.resource_id"
      @confirm="confirmTerminate"
    />

    <ChangePlanDialog v-model:server="pendingChange" @changed="reloadAll" />
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Button, Dropdown, FormControl, Spinner } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import ChangePlanDialog from '@/components/servers/ChangePlanDialog.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import TerminateDialog from '@/components/servers/TerminateDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useMigrations } from '@/composables/useMigrations'
import { useRegions } from '@/composables/useRegions'
import { useServerMapData } from '@/composables/useServerMapData'
import { useServers } from '@/composables/useServers'
import {
  STATUS_FILTERS,
  flagEmoji,
  hasMapCoords,
  regionLabel,
  specLine,
  statusVisual,
  type MapPin,
  type MapSpot,
  type ServerVisual,
} from '@/lib/serverMap'
import type { AssetRow } from '@/composables/useServers'
import type { Region } from '@/types/Region'

// The servers page: the world map is the list (FC V2). The Asset mirror feeds
// pins; Active Atlas Instances feed empty-region + spots; a slide-in panel
// carries the searchable row list. Lifecycle actions reuse useServers so the
// map page and the ⋯ menus share one command path.

const router = useRouter()

const { assets, loading, error, reload } = useServerMapData()
const { regions } = useRegions()
const { canPowerServer, canTerminateServer, canOpenServer, canCreateServer } = useCapabilities()
// Actions only — list reads come from useServerMapData (unpaginated, map-shaped).
const { refreshing, stale, busy, opening, refreshAssets, start, stop, terminate, open } = useServers()

const q = ref('')
const statusFilter = ref<ServerVisual['key'] | ''>('')
const regionFilter = ref<{ provider: string; region: string }>({ provider: '', region: '' })
const hoverId = ref<string | null>(null)
const panelOpen = ref(false)
const mapRef = ref<InstanceType<typeof ServerMap> | null>(null)

// — Rows: every non-terminated server, decorated for display. A server whose
//   region is unlisted (Draining/Disabled instance) or unplaced (no coords)
//   still rows here — it just can't pin on the map.
interface ServerRow {
  id: string
  name: string
  asset: AssetRow
  visual: ServerVisual
  specs: string
  region: Region | undefined
  regionLabel: string
  flag: string
  provider: string | null
}

const regionsByName = computed(() => new Map(regions.value.map((r) => [r.region, r])))

const rows = computed<ServerRow[]>(() =>
  assets.value.map((asset) => {
    const region = regionsByName.value.get(asset.cluster)
    return {
      id: asset.resource_id,
      name: asset.title || asset.resource_id,
      asset,
      visual: statusVisual(asset),
      specs: specLine(asset),
      region,
      regionLabel: region ? regionLabel(region) : asset.cluster,
      flag: flagEmoji(region?.country_code),
      provider: region?.provider || null,
    }
  }),
)

// — Filters. Status and region scope the map and the panel; search only
//   narrows the panel rows.
const check = () => h('span', { class: 'lucide-check size-4 text-ink-gray-7' })
const statusMenu = computed(() => [
  {
    label: 'All statuses',
    onClick: () => (statusFilter.value = ''),
    slots: { suffix: () => (statusFilter.value === '' ? check() : null) },
  },
  ...STATUS_FILTERS.map((s) => ({
    label: s.label,
    onClick: () => (statusFilter.value = s.key),
    slots: { suffix: () => (statusFilter.value === s.key ? check() : null) },
  })),
])
const statusLabelText = computed(
  () => STATUS_FILTERS.find((s) => s.key === statusFilter.value)?.label || 'Status',
)
const statusDot = computed(
  () => STATUS_FILTERS.find((s) => s.key === statusFilter.value)?.dot || 'var(--ink-gray-4)',
)

// Regions grouped by provider for the nested menu. Providerless instances
// group under "Other" so nothing disappears from the filter.
const providerGroups = computed(() => {
  const groups = new Map<string, Region[]>()
  for (const region of regions.value) {
    const provider = region.provider || 'Other'
    if (!groups.has(provider)) groups.set(provider, [])
    groups.get(provider)!.push(region)
  }
  return [...groups.entries()].map(([provider, list]) => ({ provider, regions: list }))
})

const regionMenu = computed(() => [
  {
    label: 'All regions',
    onClick: () => (regionFilter.value = { provider: '', region: '' }),
    slots: { suffix: () => (!regionFilter.value.provider && !regionFilter.value.region ? check() : null) },
  },
  ...providerGroups.value.map((group) => ({
    label: group.provider,
    submenu: [
      {
        label: `All ${group.provider} regions`,
        onClick: () => (regionFilter.value = { provider: group.provider, region: '' }),
      },
      ...group.regions.map((r) => ({
        label: `${flagEmoji(r.country_code)} ${regionLabel(r)}`.trim(),
        onClick: () => (regionFilter.value = { provider: group.provider, region: r.region }),
      })),
    ],
  })),
])
const regionLabelText = computed(() => {
  const { provider, region } = regionFilter.value
  if (!provider && !region) return 'All regions'
  if (!region) return `${provider} regions`
  const r = regionsByName.value.get(region)
  return `${provider} · ${(r ? regionLabel(r) : region).split(',')[0]}`
})

const filtered = computed(() =>
  rows.value.filter((row) => {
    if (regionFilter.value.provider && (row.provider || 'Other') !== regionFilter.value.provider) return false
    if (regionFilter.value.region && row.asset.cluster !== regionFilter.value.region) return false
    if (statusFilter.value && row.visual.key !== statusFilter.value) return false
    return true
  }),
)

// Clicking a map cluster narrows the panel to that spot ({ ids, label }).
const locationFilter = ref<{ ids: string[]; label: string } | null>(null)

const panelRows = computed(() => {
  let list = filtered.value
  if (locationFilter.value) list = list.filter((row) => locationFilter.value!.ids.includes(row.id))
  const term = q.value.trim().toLowerCase()
  if (!term) return list
  return list.filter((row) =>
    `${row.name} ${row.id} ${row.regionLabel} ${row.provider ?? ''}`.toLowerCase().includes(term),
  )
})

const pillLabel = computed(() =>
  statusFilter.value || regionFilter.value.provider || regionFilter.value.region
    ? `Servers (${filtered.value.length})`
    : `All servers (${filtered.value.length})`,
)

// — Map data. Pins carry everything their hover card shows so ServerMap stays
//   purely presentational. Only placed regions pin (0/0 = unplaced).
const pins = computed<MapPin[]>(() =>
  filtered.value
    .filter((row) => row.region && hasMapCoords(row.region))
    .map((row) => ({
      id: row.id,
      name: row.name,
      lat: row.region!.latitude!,
      lng: row.region!.longitude!,
      provider: row.provider,
      visual: row.visual,
      regionLabel: row.regionLabel,
      flag: row.flag,
      specs: row.specs,
      publicIpv4: row.asset.public_ipv4 ?? null,
      plan: row.asset.plan ?? null,
      frappeVersion: row.asset.frappe_version ?? null,
      server: row.asset,
    })),
)

// Regions with no servers show as + spots — everywhere you could deploy next.
// The status filter doesn't change what "empty" means, but a region filter
// scopes the offer too. No server:create, no offer.
const spots = computed<MapSpot[]>(() => {
  if (!canCreateServer.value) return []
  const occupied = new Set(assets.value.map((asset) => asset.cluster))
  return regions.value
    .filter((r) => !occupied.has(r.region) && hasMapCoords(r))
    .filter((r) => !regionFilter.value.provider || (r.provider || 'Other') === regionFilter.value.provider)
    .filter((r) => !regionFilter.value.region || r.region === regionFilter.value.region)
    .map((r) => ({
      id: r.region,
      lat: r.latitude!,
      lng: r.longitude!,
      provider: r.provider || null,
      regionLabel: regionLabel(r),
      flag: flagEmoji(r.country_code),
    }))
})

// — Wiring. Pin clicks lock the card (the map owns that); if the panel is
//   showing, they also narrow it to the clicked server so both stay in step.
function onOpen(id: string): void {
  if (!panelOpen.value) return
  const row = rows.value.find((r) => r.id === id)
  locationFilter.value = { ids: [id], label: row?.name ?? id }
}
function onClusterOpen(payload: { ids: string[]; label: string }): void {
  if (panelOpen.value) locationFilter.value = payload
}
function focusRow(row: ServerRow): void {
  mapRef.value?.focusPin(row.id)
}
function goNewServer(region: string): void {
  router.push({ path: '/servers/new', query: { region } })
}
// Closing the panel drops the spot filter with it.
watch(panelOpen, (isOpen) => {
  if (!isOpen) locationFilter.value = null
})

// — Commands. useServers reloads its own (reportview) list after each verb;
//   the map reads through registry, so reload that too.
function reloadAll(): void {
  reload()
  reloadMigrations()
}
async function doRefresh(): Promise<void> {
  await refreshAssets()
  reload()
}
async function doStart(server: AssetRow): Promise<void> {
  await start(server)
  reload()
}
async function doStop(server: AssetRow): Promise<void> {
  await stop(server)
  reload()
}

// Terminate confirmation — the only destructive, irreversible action.
const pendingTerminate = ref<AssetRow | null>(null)
async function confirmTerminate(server: AssetRow): Promise<void> {
  pendingTerminate.value = null
  await terminate(server)
  reload()
}

// Change plan / migrate — one dialog for both (resize in place, or move region
// with a review + optional schedule). Scheduled migrations get a row badge and a
// cancel action while they wait.
const pendingChange = ref<AssetRow | null>(null)
const { scheduledFor, cancel: cancelMigration, reload: reloadMigrations } = useMigrations()
async function doCancelMigration(server: AssetRow): Promise<void> {
  const migration = scheduledFor(server.resource_id)
  if (migration) await cancelMigration(migration)
}
</script>

<style scoped>
.sp-pill {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  height: 2.25rem;
  padding: 0 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid var(--outline-gray-2);
  background: var(--surface-elevation-1);
  box-shadow: var(--shadow-sm, 0 1px 2px rgb(0 0 0 / 0.05));
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--ink-gray-7);
  transition: background-color 150ms ease, transform 150ms cubic-bezier(0.23, 1, 0.32, 1);
}
.sp-pill:hover {
  background: var(--surface-gray-1);
}
.sp-pill:active {
  transform: scale(0.97);
}

/* "Your servers" morph: one floating card whose size change carries the whole
   story — the pill grows into the panel in place. Faster on close than open,
   one strong ease-out; the two faces just crossfade inside it. */
.sp-float {
  --sp-ease: cubic-bezier(0.23, 1, 0.32, 1);
  width: 10.5rem;
  height: 2.25rem;
  box-shadow: var(--shadow-sm, 0 1px 2px rgb(0 0 0 / 0.05));
  transition:
    width 180ms var(--sp-ease),
    height 180ms var(--sp-ease),
    border-radius 180ms var(--sp-ease),
    box-shadow 180ms var(--sp-ease);
}
.sp-float-open {
  width: 24rem;
  height: calc(100% - 2rem);
  border-radius: 0.75rem;
  box-shadow: var(--shadow-xl, 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1));
  transition-duration: 220ms;
}
.sp-float-pill {
  position: absolute;
  left: 0;
  top: 0;
  display: flex;
  height: 2.25rem;
  width: 10.5rem;
  align-items: center;
  justify-content: space-between;
  gap: 0.625rem;
  padding: 0 0.75rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--ink-gray-9);
  transition: opacity 120ms ease-out, background-color 150ms ease;
}
.sp-float-pill:hover {
  background: var(--surface-gray-1);
}
.sp-float-open .sp-float-pill {
  opacity: 0;
}
.sp-float-panel {
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 140ms ease-out, transform 220ms var(--sp-ease);
}
.sp-float-open .sp-float-panel {
  opacity: 1;
  transform: none;
  transition-delay: 40ms;
}

/* Rows cascade in as the panel opens — brief, then out of the way. */
.sp-row {
  animation: sp-row-in 250ms cubic-bezier(0.23, 1, 0.32, 1) both;
}
@keyframes sp-row-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .sp-float,
  .sp-float-pill,
  .sp-float-panel {
    transition-duration: 1ms;
    transition-delay: 0ms;
  }
  .sp-row {
    animation: none;
  }
}
</style>
