<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Button, FormControl, Checkbox, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import NoAccess from '@/components/NoAccess.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/utils/toast'

// Build a team-scoped custom role: a name plus an explicit set of capabilities
// (combinations the stock system roles don't offer, e.g. billing:view without
// billing:manage). Creating roles is gated on team:manage_members.
const router = useRouter()
const { currentTeam } = useTeam()
const { canManageTeam } = useCapabilities()

const capabilities = useCall({ url: m(API.listCapabilities), refetch: true })

const roleName = ref('')
const selected = ref(new Set())

const grouped = computed(() => {
  const groups = {}
  for (const c of capabilities.data || []) {
    const key = c.plane || 'Other'
    ;(groups[key] ??= []).push(c)
  }
  return Object.entries(groups).map(([plane, caps]) => ({ plane, caps }))
})

function toggle(name) {
  const next = new Set(selected.value)
  next.has(name) ? next.delete(name) : next.add(name)
  selected.value = next
}

const create = useCall({ url: m(API.createCustomRole), immediate: false })
const canSave = computed(() => roleName.value.trim() && selected.value.size > 0)

async function save() {
  if (!canSave.value) return
  try {
    await create.submit({
      team: currentTeam.value,
      role_name: roleName.value.trim(),
      capabilities: [...selected.value],
    })
    successToast('Custom role created.')
    router.push({ name: 'Roles' })
  } catch (e) {
    errorToast(e, 'Could not create the role.')
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Team' }, { label: 'Roles' }, { label: 'New' }]">
      <template #actions>
        <Button variant="ghost" label="Cancel" @click="router.push({ name: 'Roles' })" />
        <Button
          v-if="canManageTeam"
          variant="solid"
          label="Create role"
          :loading="create.loading"
          :disabled="!canSave"
          @click="save"
        />
      </template>
    </PageHeader>

    <NoAccess
      v-if="!canManageTeam"
      roles="Owner or Admin"
      message="Only members who can manage the team may create roles."
    />

    <div v-else class="body-container space-y-6 pb-40 pt-5">
      <FormControl
        v-model="roleName"
        label="Role name"
        placeholder="e.g. Finance viewer"
        class="max-w-sm"
      />

      <div v-if="capabilities.loading && !capabilities.data" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <div v-else class="space-y-5">
        <p class="text-p-sm text-ink-gray-5">
          Pick the capabilities this role grants ({{ selected.size }} selected).
        </p>
        <section v-for="group in grouped" :key="group.plane" class="space-y-2">
          <p class="text-p-sm font-medium uppercase tracking-wide text-ink-gray-5">
            {{ group.plane }}
          </p>
          <div class="grid gap-2 sm:grid-cols-2">
            <label
              v-for="cap in group.caps"
              :key="cap.name"
              class="flex cursor-pointer items-start gap-2 rounded border border-outline-gray-1 px-3 py-2 hover:border-outline-gray-2"
            >
              <Checkbox
                :modelValue="selected.has(cap.name)"
                @update:modelValue="toggle(cap.name)"
              />
              <span class="min-w-0">
                <span class="block text-sm text-ink-gray-8">{{ cap.name }}</span>
                <span v-if="cap.description" class="block text-p-sm text-ink-gray-5">
                  {{ cap.description }}
                </span>
              </span>
            </label>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
