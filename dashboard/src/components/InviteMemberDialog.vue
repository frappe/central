<script setup>
import { ref, computed } from 'vue'
import { Dialog, Button, FormControl } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCall } from 'frappe-ui'
import { successToast, errorToast } from '@/utils/toast'

// Invite by email + role. The backend creates a Team Invitation; the invitee
// becomes a member on accept (Team.add_member_from_invitation).
const props = defineProps({
  roles: { type: Array, default: () => [] }, // [{name, role_name}]
})
const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['done'])
const { currentTeam } = useTeam()

const email = ref('')
const role = ref('')

const roleOptions = computed(() =>
  props.roles.map((r) => ({ label: r.role_name || r.name, value: r.name })),
)

const invite = useCall({ url: m(API.inviteMember), method: 'POST', immediate: false })

async function submit() {
  if (!email.value || !role.value) return
  try {
    await invite.submit({ team: currentTeam.value, email: email.value, role: role.value })
    successToast(`Invitation sent to ${email.value}.`)
    email.value = ''
    role.value = ''
    open.value = false
    emit('done')
  } catch (e) {
    errorToast(e, 'Could not send the invite.')
  }
}
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Invite member' }">
    <template #body-content>
      <div class="space-y-4">
        <FormControl
          v-model="email"
          type="email"
          label="Email"
          placeholder="teammate@example.com"
        />
        <FormControl
          v-model="role"
          type="select"
          label="Role"
          :options="roleOptions"
          placeholder="Select a role"
        />
      </div>
    </template>
    <template #actions>
      <Button
        variant="solid"
        label="Send invite"
        class="w-full"
        :loading="invite.loading"
        :disabled="!email || !role"
        @click="submit"
      />
    </template>
  </Dialog>
</template>
