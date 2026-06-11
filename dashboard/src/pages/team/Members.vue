<script setup>
import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { Badge, Button, Dropdown, Select, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import InviteMemberDialog from '@/components/InviteMemberDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/utils/toast'

const { currentTeam } = useTeam()
const { canManageTeam } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const members = useCall({ url: m(API.listTeamMembers), params, refetch: true })
const roles = useCall({ url: m(API.listRoles), params, refetch: true })

const setRole = useCall({ url: m(API.setMemberRole), immediate: false })
const setStatus = useCall({ url: m(API.setMemberStatus), immediate: false })
const remove = useCall({ url: m(API.removeMember), immediate: false })
const busy = computed(() => setRole.loading || setStatus.loading || remove.loading)

async function changeRole(mem, role) {
  try {
    await setRole.submit({ team: currentTeam.value, user: mem.user, role })
    successToast('Role updated.')
    members.reload()
  } catch (e) {
    errorToast(e)
  }
}
async function toggleStatus(mem) {
  const next = mem.status === 'Active' ? 'Suspended' : 'Active'
  try {
    await setStatus.submit({ team: currentTeam.value, user: mem.user, status: next })
    successToast(`Member ${next.toLowerCase()}.`)
    members.reload()
  } catch (e) {
    errorToast(e)
  }
}
async function removeMember(mem) {
  try {
    await remove.submit({ team: currentTeam.value, user: mem.user })
    successToast('Member removed.')
    members.reload()
  } catch (e) {
    errorToast(e)
  }
}

// Role is changed inline (the explicit member→role control); the ⋯ menu carries
// only status/remove. Owner is immutable here (backend enforces a single Owner).
function rowActions(mem) {
  if (mem.is_owner) return []
  return [
    { label: mem.status === 'Active' ? 'Suspend' : 'Activate', onClick: () => toggleStatus(mem) },
    { label: 'Remove', onClick: () => removeMember(mem) },
  ]
}

const showInvite = ref(false)
const roleLabel = (name) =>
  (roles.data || []).find((r) => r.name === name)?.role_name || name
const roleOptions = computed(() =>
  (roles.data || []).map((r) => ({ label: r.role_name || r.name, value: r.name })),
)
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Team' }, { label: 'Members' }]">
      <template #actions>
        <Button v-if="canManageTeam" variant="solid" label="Invite" @click="showInvite = true" />
      </template>
    </PageHeader>

    <div class="body-container space-y-2 pb-40 pt-5">
      <div v-if="members.loading && !members.data" class="space-y-3">
        <LoadingText :lines="4" />
      </div>

      <ul v-else class="space-y-2">
        <li
          v-for="mem in members.data"
          :key="mem.user"
          class="flex items-center gap-3 rounded border border-outline-gray-1 px-4 py-3"
        >
          <div
            class="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-gray-3 text-sm text-ink-gray-7"
          >
            {{ (mem.user || '?').charAt(0).toUpperCase() }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="truncate text-sm text-ink-gray-8">{{ mem.user }}</p>
              <Badge v-if="mem.is_owner" theme="green" label="Owner" />
              <Badge v-if="mem.status !== 'Active'" theme="orange" :label="mem.status" />
            </div>
          </div>

          <!-- Explicit member → role control. -->
          <div class="flex items-center gap-1">
            <span class="hidden text-p-sm text-ink-gray-5 sm:inline">Role</span>
            <Select
              v-if="canManageTeam && !mem.is_owner"
              :modelValue="mem.role"
              :options="roleOptions"
              :disabled="busy"
              @update:modelValue="(v) => changeRole(mem, v)"
            />
            <Badge v-else theme="gray" :label="roleLabel(mem.role)" />
          </div>

          <Dropdown
            v-if="canManageTeam && !mem.is_owner"
            :options="rowActions(mem)"
            placement="right"
          >
            <Button variant="ghost" :loading="busy">
              <template #icon><span class="lucide-ellipsis size-4" /></template>
            </Button>
          </Dropdown>
        </li>
      </ul>
    </div>

    <InviteMemberDialog v-model="showInvite" :roles="roles.data || []" @done="members.reload()" />
  </div>
</template>
