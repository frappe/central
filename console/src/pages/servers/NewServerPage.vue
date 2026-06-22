<script setup lang="ts">
import { computed, ref } from 'vue'
import { Badge, Button, FormControl } from 'frappe-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import { useRegions } from '@/composables/useRegions'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { SIZE_PRESETS, presetSpecs, type SizePreset } from '@/lib/plans'

// New server. Region is the set of available Atlas Instances; size is a preset
// (no Plan doctype on Central yet). Create routes through central.api.servers
// .create_server → the region's Atlas → a real VM (dev fake provider), which is
// mirrored back so it shows on the Servers list.
const router = useRouter()
const { regions, loading } = useRegions()
const { create, creating } = useServers()
const { canCreateServer } = useCapabilities()

const selectedRegion = ref<string | null>(null)
const name = ref('')
const selectedSlug = ref<string>(SIZE_PRESETS[0].slug)

const selectedSize = computed<SizePreset>(
  () => SIZE_PRESETS.find((p) => p.slug === selectedSlug.value) ?? SIZE_PRESETS[0],
)

const canSubmit = computed(
  () => canCreateServer.value && !!selectedRegion.value && name.value.trim().length > 0,
)

async function submit() {
  if (!canSubmit.value || !selectedRegion.value) return
  const size = selectedSize.value
  try {
    await create({
      region: selectedRegion.value,
      title: name.value.trim(),
      vcpus: size.vcpus,
      memory_megabytes: size.memoryMegabytes,
      disk_gigabytes: size.diskGigabytes,
      cpu_max_cores: size.cpuMaxCores,
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

      <!-- Size -->
      <section class="space-y-3">
        <div class="flex items-center gap-2">
          <span class="lucide-cpu size-4 text-ink-gray-6" aria-hidden="true" />
          <h2 class="text-base font-medium text-ink-gray-8">Size</h2>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <button
            v-for="preset in SIZE_PRESETS"
            :key="preset.slug"
            type="button"
            class="flex flex-col gap-1 rounded-lg border px-4 py-3 text-left transition-colors"
            :class="
              selectedSlug === preset.slug
                ? 'border-outline-gray-4 bg-surface-gray-2'
                : 'border-outline-gray-2 hover:border-outline-gray-3'
            "
            @click="selectedSlug = preset.slug"
          >
            <span class="font-medium text-ink-gray-9">{{ preset.label }}</span>
            <span class="text-p-sm text-ink-gray-5">{{ presetSpecs(preset) }}</span>
          </button>
        </div>
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
