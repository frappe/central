<script setup lang="ts">
import { computed } from 'vue'
import { Dialog } from 'frappe-ui'
import type { Server } from '@/types'

// Destructive, irreversible confirm for terminating a server. Controlled by the
// page: pass the pending server (or null) via v-model:server.
const props = defineProps<{
  server: Server | null
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:server': [server: Server | null]
  confirm: [server: Server]
}>()

const open = computed({
  get: () => !!props.server,
  set: (v: boolean) => {
    if (!v) emit('update:server', null)
  },
})

const name = computed(() => props.server?.title || props.server?.resource_id || '')

const dialogOptions = computed(() => ({
  title: 'Terminate server',
  message: `Permanently destroy ${name.value}? This can't be undone.`,
  actions: [
    {
      label: 'Terminate',
      variant: 'solid' as const,
      theme: 'red' as const,
      loading: props.loading,
      onClick: () => {
        if (props.server) emit('confirm', props.server)
      },
    },
  ],
}))
</script>

<template>
  <Dialog v-model="open" :options="dialogOptions" />
</template>
