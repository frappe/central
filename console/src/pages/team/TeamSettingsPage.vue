<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Dialog, FormControl } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useCapabilities } from '@/composables/useCapabilities'

// Team settings: rename (team:edit), transfer ownership (owner only), and the
// danger-zone delete (team:delete). Each control is shown only when the signed-in
// user may use it — the server enforces the same gates.
const router = useRouter()
const { activeTeam, activeTeamLabel } = useSession()
const { isOwner, saving, rename, transferOwnership, deleteTeam } = useTeamSettings()
const { members } = useTeamMembers()
const { canEditTeam, canDeleteTeam } = useCapabilities()

const name = ref(activeTeamLabel.value)
watch([activeTeam, activeTeamLabel], () => {
  name.value = activeTeamLabel.value
})
const renameChanged = computed(() => !!name.value.trim() && name.value.trim() !== activeTeamLabel.value)

const transferTargets = computed(() =>
  members.value
    .filter((m) => m.status === 'Active' && !m.is_owner)
    .map((m) => ({ label: m.user, value: m.user })),
)
const newOwner = ref('')

const confirmTransfer = ref(false)
const confirmDelete = ref(false)

const transferOptions = computed(() => ({
  title: 'Transfer ownership',
  message: newOwner.value
    ? `Make ${newOwner.value} the owner of this team? You will become an Admin.`
    : '',
  actions: [
    { label: 'Transfer ownership', variant: 'solid' as const, loading: saving.value, onClick: onTransfer },
  ],
}))

const deleteOptions = computed(() => ({
  title: 'Delete team',
  message: `Permanently delete “${activeTeamLabel.value}”? This can't be undone.`,
  actions: [
    { label: 'Delete team', variant: 'solid' as const, theme: 'red' as const, loading: saving.value, onClick: onDelete },
  ],
}))

async function onTransfer() {
  if (!newOwner.value) return
  if (await transferOwnership(newOwner.value)) {
    confirmTransfer.value = false
    newOwner.value = ''
  }
}

async function onDelete() {
  if (await deleteTeam()) {
    confirmDelete.value = false
    router.push('/servers')
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Team settings" subtitle="Name, ownership, and deletion." />

    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div class="mx-auto max-w-2xl space-y-6">
        <!-- General -->
        <section class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5">
          <h2 class="text-base font-semibold text-ink-gray-9">General</h2>
          <div class="mt-4 flex items-end gap-3">
            <FormControl v-model="name" label="Team name" class="flex-1" :disabled="!canEditTeam" />
            <Button
              variant="solid"
              label="Save"
              :loading="saving"
              :disabled="!canEditTeam || !renameChanged"
              @click="rename(name.trim())"
            />
          </div>
          <p v-if="!canEditTeam" class="mt-2 text-xs text-ink-gray-5">Requires the Admin or Owner role.</p>
        </section>

        <!-- Transfer ownership (owner only) -->
        <section
          v-if="isOwner"
          class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5"
        >
          <h2 class="text-base font-semibold text-ink-gray-9">Transfer ownership</h2>
          <p class="mt-1 text-p-sm text-ink-gray-5">
            Hand the Owner role to another active member. You become an Admin.
          </p>
          <div class="mt-4 flex items-end gap-3">
            <FormControl
              v-model="newOwner"
              type="select"
              label="New owner"
              class="flex-1"
              :options="transferTargets"
              placeholder="Choose a member"
            />
            <Button label="Transfer" :disabled="!newOwner" @click="confirmTransfer = true" />
          </div>
          <p v-if="!transferTargets.length" class="mt-2 text-xs text-ink-gray-5">
            Add another active member first.
          </p>
        </section>

        <!-- Danger zone -->
        <section
          v-if="canDeleteTeam"
          class="rounded-lg border border-outline-red-1 bg-surface-elevation-1 p-5"
        >
          <h2 class="text-base font-semibold text-ink-gray-9">Danger zone</h2>
          <p class="mt-1 text-p-sm text-ink-gray-5">
            Deleting a team is permanent and removes everyone's access. Its servers and sites must be
            removed first.
          </p>
          <Button class="mt-4" theme="red" variant="solid" label="Delete this team" @click="confirmDelete = true" />
        </section>
      </div>
    </div>

    <Dialog
      v-model="confirmTransfer"
      :title="transferOptions.title"
      :message="transferOptions.message"
      :actions="transferOptions.actions"
    />
    <Dialog
      v-model="confirmDelete"
      :title="deleteOptions.title"
      :message="deleteOptions.message"
      :actions="deleteOptions.actions"
    />
  </div>
</template>
