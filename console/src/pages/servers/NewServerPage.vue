<script setup lang="ts">
import { ref } from 'vue'
import { Badge, Button } from 'frappe-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import { useRegions } from '@/composables/useRegions'

// New server — region selection only, for now. The region set is the available
// Atlas Instances (central.atlas.list_instances). Provisioning itself is not yet
// wired: there is no Atlas create contract (AtlasClient has no create_vm) and no
// plan/provider doctype, so we stop at picking where it would live and surface
// that clearly rather than faking a create.
const router = useRouter()
const { regions, loading } = useRegions()

const selectedRegion = ref<string | null>(null)
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="New server" subtitle="Pick where it lives. You can resize later.">
      <template #actions>
        <Button label="Back" icon-left="lucide-arrow-left" @click="router.push('/servers')" />
      </template>
    </PageHeader>

    <div class="page-body max-w-[760px] space-y-6 py-6">
      <section class="space-y-3">
        <div class="flex items-center gap-2">
          <span class="lucide-globe size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Select a region</h2>
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

      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-gray-1 px-4 py-3">
        <p class="text-p-sm text-ink-gray-5">
          Provisioning isn't available yet — region selection is wired, the create
          step lands when the Atlas provisioning API ships.
        </p>
        <Button variant="solid" label="Create server" :disabled="true" />
      </div>
    </div>
  </div>
</template>
