<script setup lang="ts">
import { ref } from 'vue'
import { Button } from 'frappe-ui'
import Skeleton from '../common/Skeleton.vue'
import RoleMatrix from '@/components/team/RoleMatrix.vue'
import RoleBuilderDialog from '@/components/team/RoleBuilderDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamRoles } from '@/composables/useTeamRoles'
import type { TeamRoleRow } from '@/types/api'

const { roles, capabilities, loading, error, reload, deleteRole } = useTeamRoles()
const { canManageMembers } = useCapabilities()

const builderOpen = ref(false)
const deleting = ref('')

async function onDeleteRole(role: TeamRoleRow): Promise<void> {
  deleting.value = role.name
  try {
    await deleteRole(role.name, role.role_name)
  } finally {
    deleting.value = ''
  }
}
</script>

<template>
  <div class="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
    <div class="mb-4 flex items-center justify-between gap-3">
      <p class="text-p-sm text-ink-gray-5">
        Every role and exactly what it can do. Roles are named sets of capabilities.
      </p>
      <Button
        v-if="canManageMembers"
        variant="solid"
        label="New role"
        icon-left="lucide-plus"
        @click="builderOpen = true"
      />
    </div>

    <Skeleton v-if="loading" class="h-64 rounded-lg" />

    <div
      v-else-if="error"
      class="flex items-center justify-between gap-3 rounded-lg border border-outline-gray-2 px-4 py-3"
      role="alert"
    >
      <p class="text-p-sm text-ink-red-7">{{ error }}</p>
      <Button label="Retry" variant="ghost" @click="reload" />
    </div>

    <RoleMatrix
      v-else
      :roles="roles"
      :capabilities="capabilities"
      :can-manage="canManageMembers"
      :deleting-name="deleting"
      @delete="onDeleteRole"
    />
  </div>

  <RoleBuilderDialog v-model:open="builderOpen" @created="reload" />
</template>
