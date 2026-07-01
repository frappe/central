<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Dialog, FormControl, Checkbox } from 'frappe-ui'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { groupCapabilitiesByPlane } from '@/lib/capabilities'

// Build a custom team role: a name + any subset of capabilities. Central closes
// the set under its implications on save (e.g. server:create pulls in
// server:view + cluster:view), so the user only ticks what they mean.
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [v: boolean]; created: [] }>()

const { capabilities, creating, createRole } = useTeamRoles()

const open = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

const roleName = ref('')
const picked = ref<string[]>([])

watch(open, (isOpen) => {
  if (isOpen) {
    roleName.value = ''
    picked.value = []
  }
})

const groups = computed(() => groupCapabilitiesByPlane(capabilities.value))

function toggle(cap: string, checked: boolean) {
  if (checked) {
    if (!picked.value.includes(cap)) picked.value = [...picked.value, cap]
  } else {
    picked.value = picked.value.filter((c) => c !== cap)
  }
}

const canSubmit = computed(() => roleName.value.trim().length > 0 && picked.value.length > 0)

const dialogOptions = computed(() => ({
  title: 'New custom role',
  size: 'xl' as const,
  actions: [
    {
      label: 'Create role',
      variant: 'solid' as const,
      loading: creating.value,
      disabled: !canSubmit.value,
      onClick: submit,
    },
  ],
}))

async function submit() {
  if (!canSubmit.value) return
  try {
    await createRole(roleName.value.trim(), picked.value)
    emit('created')
    open.value = false
  } catch {
    /* toast already surfaced in the composable */
  }
}
</script>

<template>
  <Dialog
    v-model="open"
    :title="dialogOptions.title"
    :size="dialogOptions.size"
    :actions="dialogOptions.actions"
  >
    <template #default>
      <div class="space-y-5">
        <FormControl v-model="roleName" label="Role name" placeholder="e.g. Release Manager" />

        <div>
          <p class="mb-1 text-p-sm font-medium text-ink-gray-7">Capabilities</p>
          <p class="mb-3 text-xs text-ink-gray-4">
            Pick what this role can do. Dependencies (like “view” for an “act on”) are added automatically.
          </p>
          <div class="max-h-[50vh] space-y-4 overflow-y-auto">
            <section v-for="group in groups" :key="group.plane">
              <h4 class="mb-2 text-xs font-medium uppercase tracking-wide text-ink-gray-4">
                {{ group.label }}
              </h4>
              <ul class="space-y-2">
                <li v-for="cap in group.caps" :key="cap.name" class="flex gap-2">
                  <Checkbox
                    :model-value="picked.includes(cap.name)"
                    class="mt-0.5 shrink-0"
                    @update:model-value="toggle(cap.name, Boolean($event))"
                  />
                  <div class="min-w-0">
                    <p class="font-mono text-xs text-ink-gray-7">{{ cap.name }}</p>
                    <p class="text-p-sm text-ink-gray-5">{{ cap.description }}</p>
                  </div>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>
