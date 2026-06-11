<script setup>
import { ref, computed } from 'vue'
import { Badge, Button, Dialog, FormControl } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import MockBanner from '@/components/MockBanner.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { requestTheme } from '@/utils/status'
import { successToast } from '@/utils/toast'
import { MOCK_ACCESS_REQUESTS, MOCK_CLUSTERS } from './mock'

// 🟡 Mock. Request a cluster not in allowed_clusters. An operator reviews it (or
// it auto-resolves on the next trust-tier promotion that widens the set). The
// approval widens the team's entitlement slice in the real model.
const { canManageAtlas } = useCapabilities()

const requests = ref([...MOCK_ACCESS_REQUESTS])
const lockedClusters = MOCK_CLUSTERS.filter((c) => !c.allowed)

const showNew = ref(false)
const form = ref({ cluster: '', reason: '' })
const clusterOptions = lockedClusters.map((c) => ({ label: c.label, value: c.slug }))
const canSubmit = computed(() => form.value.cluster && form.value.reason.trim())

function submit() {
  if (!canSubmit.value) return
  const c = MOCK_CLUSTERS.find((x) => x.slug === form.value.cluster)
  requests.value.unshift({
    cluster: c.slug,
    cluster_label: c.label,
    reason: form.value.reason.trim(),
    status: 'pending',
    requested: new Date().toISOString().slice(0, 10),
  })
  successToast('Request submitted.')
  form.value = { cluster: '', reason: '' }
  showNew.value = false
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Atlas' }, { label: 'Access Requests' }]">
      <template #actions>
        <Button
          v-if="canManageAtlas"
          variant="solid"
          label="Request access"
          :disabled="!lockedClusters.length"
          @click="showNew = true"
        />
      </template>
    </PageHeader>

    <div class="body-container space-y-4 pb-40 pt-5">
      <MockBanner />

      <div
        v-if="!requests.length"
        class="rounded border border-dashed border-outline-gray-2 px-6 py-12 text-center text-p-sm text-ink-gray-5"
      >
        No access requests.
      </div>

      <ul v-else class="space-y-2">
        <li
          v-for="(r, i) in requests"
          :key="i"
          class="flex items-center justify-between gap-3 rounded border border-outline-gray-1 px-4 py-3"
        >
          <div class="min-w-0">
            <p class="truncate text-sm text-ink-gray-8">{{ r.cluster_label }}</p>
            <p class="text-p-sm text-ink-gray-5">
              {{ r.reason }} · requested {{ r.requested }}
              <span v-if="r.note" class="text-ink-gray-4">({{ r.note }})</span>
            </p>
          </div>
          <Badge :theme="requestTheme(r.status)" :label="r.status" />
        </li>
      </ul>
    </div>

    <Dialog v-model="showNew" :options="{ title: 'Request cluster access' }">
      <template #body-content>
        <div class="space-y-4">
          <FormControl
            v-model="form.cluster"
            type="select"
            label="Cluster"
            :options="clusterOptions"
            placeholder="Select a locked cluster"
          />
          <FormControl
            v-model="form.reason"
            type="textarea"
            label="Reason"
            placeholder="e.g. GDPR data residency for EU customers"
          />
          <p class="text-p-sm text-ink-gray-5">
            Approval may require reaching a higher trust tier. See Trust Tier.
          </p>
        </div>
      </template>
      <template #actions>
        <Button
          variant="solid"
          label="Submit request"
          class="w-full"
          :disabled="!canSubmit"
          @click="submit"
        />
      </template>
    </Dialog>
  </div>
</template>
