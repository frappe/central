<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Button } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import MockBanner from '@/components/MockBanner.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast } from '@/utils/toast'
import { MOCK_CLUSTERS } from './mock'

// 🟡 Mock. The current region is the default for new provisions. Switching is
// allowed only among the team's allowed_clusters (✅ from get_trust_tier in the
// real model); locked clusters link to Access Requests. Switching doesn't move
// existing resources — it only changes the default target.
const router = useRouter()
const { canManageAtlas } = useCapabilities()

const current = ref('mumbai')

function switchTo(slug) {
  current.value = slug
  successToast(`Default region set to ${MOCK_CLUSTERS.find((c) => c.slug === slug)?.label}.`)
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Atlas' }, { label: 'Region' }]" />

    <div class="body-container space-y-5 pb-40 pt-5">
      <MockBanner />

      <p class="text-sm text-ink-gray-6">
        New resources default to your current region. Switching changes only the default —
        existing resources stay where they are.
      </p>

      <ul class="space-y-2">
        <li
          v-for="c in MOCK_CLUSTERS"
          :key="c.slug"
          class="flex items-center gap-3 rounded border px-4 py-3"
          :class="c.slug === current ? 'border-outline-gray-3 bg-surface-gray-1' : 'border-outline-gray-1'"
        >
          <span
            class="size-2.5 shrink-0 rounded-full"
            :class="c.slug === current ? 'bg-surface-green-5' : 'bg-surface-gray-3'"
          />
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="truncate text-sm text-ink-gray-8">{{ c.label }}</p>
              <span v-if="!c.allowed" class="lucide-lock size-3.5 text-ink-gray-5" />
            </div>
            <p class="text-p-sm text-ink-gray-5">
              <template v-if="c.allowed">{{ c.status }} · {{ c.resources }} resource(s)</template>
              <template v-else>Not in your tier</template>
            </p>
          </div>

          <Badge v-if="c.slug === current" theme="green" label="Current" />
          <Button
            v-else-if="c.allowed && canManageAtlas"
            variant="subtle"
            label="Switch"
            @click="switchTo(c.slug)"
          />
          <Button
            v-else-if="!c.allowed"
            variant="ghost"
            label="Request access"
            @click="router.push({ name: 'AtlasAccess' })"
          />
        </li>
      </ul>
    </div>
  </div>
</template>
