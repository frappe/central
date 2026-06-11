<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Badge, Button, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'

// Capability matrix: which role grants which capability. System roles are fixed;
// custom roles are team-scoped combinations built in the role builder.
const router = useRouter()
const { currentTeam } = useTeam()
const { canManageTeam } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const roles = useCall({ url: m(API.listRoles), params, refetch: true })
const capabilities = useCall({ url: m(API.listCapabilities), refetch: true })

const loading = computed(
  () => (roles.loading && !roles.data) || (capabilities.loading && !capabilities.data),
)

// Group capabilities by plane (billing / team / compute) for a legible matrix.
const grouped = computed(() => {
  const groups = {}
  for (const c of capabilities.data || []) {
    const key = c.plane || 'Other'
    ;(groups[key] ??= []).push(c)
  }
  return Object.entries(groups).map(([plane, caps]) => ({ plane, caps }))
})

function grants(role, capName) {
  return (role.capabilities || []).includes(capName)
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Team' }, { label: 'Roles' }]">
      <template #actions>
        <Button
          v-if="canManageTeam"
          variant="solid"
          label="New role"
          @click="router.push({ name: 'NewRole' })"
        />
      </template>
    </PageHeader>

    <div class="min-h-0 flex-1 overflow-auto">
      <div v-if="loading" class="body-container space-y-3 pt-5">
        <LoadingText :lines="8" />
      </div>

      <table v-else class="w-full border-collapse text-sm">
        <thead class="sticky top-0 bg-surface-white">
          <tr class="border-b border-outline-gray-2 text-left">
            <th class="px-4 py-3 font-medium text-ink-gray-7">Capability</th>
            <th
              v-for="r in roles.data"
              :key="r.name"
              class="px-3 py-3 text-center font-medium text-ink-gray-7"
            >
              <div class="flex flex-col items-center gap-1">
                <span>{{ r.role_name || r.name }}</span>
                <Badge v-if="!r.is_system" theme="blue" label="Custom" />
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in grouped" :key="group.plane">
            <tr class="bg-surface-gray-1">
              <td
                :colspan="(roles.data?.length || 0) + 1"
                class="px-4 py-1.5 text-p-sm font-medium uppercase tracking-wide text-ink-gray-5"
              >
                {{ group.plane }}
              </td>
            </tr>
            <tr
              v-for="cap in group.caps"
              :key="cap.name"
              class="border-b border-outline-gray-1"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink-gray-8">{{ cap.name }}</p>
                <p v-if="cap.description" class="text-p-sm text-ink-gray-5">{{ cap.description }}</p>
              </td>
              <td v-for="r in roles.data" :key="r.name" class="px-3 py-2.5 text-center">
                <span
                  v-if="grants(r, cap.name)"
                  class="lucide-check size-4 text-ink-green-3"
                  aria-label="granted"
                />
                <span v-else class="text-ink-gray-3">·</span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
