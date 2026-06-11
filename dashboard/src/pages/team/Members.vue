<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Badge, Button, Select, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import SplitView from '@/components/SplitView.vue'
import InviteMemberDialog from '@/components/InviteMemberDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/utils/toast'

// Merged Members + Roles: the roster lives left; selecting a member opens a
// detail panel where you assign a role AND immediately see what that role grants
// (its capabilities). Roles aren't a separate screen — they're shown in context
// of the person you're giving them to.
const router = useRouter()
const { currentTeam } = useTeam()
const { canManageTeam } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const members = useCall({ url: m(API.listTeamMembers), params, refetch: true })
const roles = useCall({ url: m(API.listRoles), params, refetch: true })
const capabilities = useCall({ url: m(API.listCapabilities), refetch: true })

// ── Mutations ──
const setRole = useCall({ url: m(API.setMemberRole), immediate: false })
const setStatus = useCall({ url: m(API.setMemberStatus), immediate: false })
const remove = useCall({ url: m(API.removeMember), immediate: false })
const busy = computed(() => setRole.loading || setStatus.loading || remove.loading)

async function changeRole(mem, role) {
  try {
    await setRole.submit({ team: currentTeam.value, user: mem.user, role })
    successToast('Role updated.')
    await members.reload()
    if (selected.value?.user === mem.user) selected.value = { ...mem, role }
  } catch (e) {
    errorToast(e)
  }
}
async function toggleStatus(mem) {
  const next = mem.status === 'Active' ? 'Suspended' : 'Active'
  try {
    await setStatus.submit({ team: currentTeam.value, user: mem.user, status: next })
    successToast(`Member ${next.toLowerCase()}.`)
    await members.reload()
    if (selected.value?.user === mem.user) selected.value = { ...mem, status: next }
  } catch (e) {
    errorToast(e)
  }
}
async function removeMember(mem) {
  try {
    await remove.submit({ team: currentTeam.value, user: mem.user })
    successToast('Member removed.')
    selected.value = null
    members.reload()
  } catch (e) {
    errorToast(e)
  }
}

// ── Selection / role lookups ──
const selected = ref(null)
const detailOpen = computed({
  get: () => !!selected.value,
  set: (v) => { if (!v) selected.value = null },
})
function selectRow(mem) {
  selected.value = mem
}

const roleOptions = computed(() =>
  (roles.data || []).map((r) => ({ label: r.role_name || r.name, value: r.name })),
)
const roleLabel = (name) => (roles.data || []).find((r) => r.name === name)?.role_name || name
const capDescription = (name) =>
  (capabilities.data || []).find((c) => c.name === name)?.description || ''

// Capabilities granted by the selected member's role — the live "what does this
// role allow" preview that updates as you change the assignment.
const selectedRoleCaps = computed(() => {
  const role = (roles.data || []).find((r) => r.name === selected.value?.role)
  return role?.capabilities || []
})

const showInvite = ref(false)
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Team' }, { label: 'Members & Roles' }]">
      <template #actions>
        <Button
          v-if="canManageTeam"
          variant="subtle"
          label="New role"
          @click="router.push({ name: 'NewRole' })"
        />
        <Button v-if="canManageTeam" variant="solid" label="Invite" @click="showInvite = true" />
      </template>
    </PageHeader>

    <SplitView v-model:open="detailOpen" class="flex-1">
      <!-- ROSTER -->
      <template #list>
        <div v-if="members.loading && !members.data" class="space-y-3 p-4">
          <LoadingText :lines="5" />
        </div>
        <ul v-else class="divide-y divide-outline-gray-1">
          <li
            v-for="mem in members.data"
            :key="mem.user"
            class="flex cursor-pointer items-center gap-3 px-4 py-3 hover:bg-surface-gray-1"
            :class="selected?.user === mem.user && 'bg-surface-gray-2'"
            @click="selectRow(mem)"
          >
            <div class="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-gray-3 text-sm text-ink-gray-7">
              {{ (mem.user || '?').charAt(0).toUpperCase() }}
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm text-ink-gray-8">{{ mem.user }}</p>
              <p class="text-p-sm text-ink-gray-5">{{ roleLabel(mem.role) }}</p>
            </div>
            <Badge v-if="mem.is_owner" theme="green" label="Owner" />
            <Badge v-else-if="mem.status !== 'Active'" theme="orange" :label="mem.status" />
            <span class="lucide-chevron-right size-4 text-ink-gray-4" />
          </li>
        </ul>
      </template>

      <!-- MEMBER + ROLE DETAIL -->
      <template #detail>
        <div v-if="selected" class="flex flex-col gap-5 p-4">
          <header class="flex items-center gap-3">
            <div class="flex size-11 shrink-0 items-center justify-center rounded-full bg-surface-gray-3 text-base text-ink-gray-7">
              {{ (selected.user || '?').charAt(0).toUpperCase() }}
            </div>
            <div class="min-w-0">
              <p class="truncate text-base text-ink-gray-9">{{ selected.user }}</p>
              <div class="mt-0.5 flex items-center gap-1.5">
                <Badge v-if="selected.is_owner" theme="green" label="Owner" />
                <Badge
                  :theme="selected.status === 'Active' ? 'green' : 'orange'"
                  :label="selected.status"
                />
              </div>
            </div>
          </header>

          <!-- Role assignment -->
          <div class="space-y-2">
            <p class="text-p-sm font-medium text-ink-gray-6">Role</p>
            <Select
              v-if="canManageTeam && !selected.is_owner"
              :modelValue="selected.role"
              :options="roleOptions"
              :disabled="busy"
              @update:modelValue="(v) => changeRole(selected, v)"
            />
            <Badge v-else size="lg" theme="gray" :label="roleLabel(selected.role)" />
            <p v-if="selected.is_owner" class="text-p-sm text-ink-gray-5">
              The Owner role can’t be reassigned here.
            </p>
          </div>

          <!-- What this role grants — updates live as the role changes -->
          <div class="rounded border border-outline-gray-1">
            <header class="border-b border-outline-gray-1 px-3 py-2">
              <p class="text-p-sm font-medium text-ink-gray-6">
                {{ roleLabel(selected.role) }} can
              </p>
            </header>
            <ul v-if="selectedRoleCaps.length" class="divide-y divide-outline-gray-1">
              <li v-for="cap in selectedRoleCaps" :key="cap" class="flex items-start gap-2 px-3 py-2">
                <span class="lucide-check mt-0.5 size-3.5 shrink-0 text-ink-green-3" />
                <span class="min-w-0">
                  <span class="block text-sm text-ink-gray-8">{{ cap }}</span>
                  <span v-if="capDescription(cap)" class="block text-p-sm text-ink-gray-5">
                    {{ capDescription(cap) }}
                  </span>
                </span>
              </li>
            </ul>
            <p v-else class="px-3 py-4 text-p-sm text-ink-gray-5">
              This role grants no capabilities.
            </p>
          </div>

          <!-- Member actions -->
          <div v-if="canManageTeam && !selected.is_owner" class="flex gap-2">
            <Button
              :label="selected.status === 'Active' ? 'Suspend' : 'Activate'"
              :loading="busy"
              @click="toggleStatus(selected)"
            />
            <Button theme="red" variant="subtle" label="Remove" :loading="busy" @click="removeMember(selected)" />
          </div>
        </div>

        <div v-else class="flex h-full items-center justify-center p-8 text-center text-p-sm text-ink-gray-5">
          Select a member to view and assign their role.
        </div>
      </template>
    </SplitView>

    <InviteMemberDialog v-model="showInvite" :roles="roles.data || []" @done="members.reload()" />
  </div>
</template>
