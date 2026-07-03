<script setup lang="ts">
import { computed } from 'vue'
import { Button, Dropdown } from 'frappe-ui'
import { canStart, canStop, isMigrating, isResizing, isTerminated } from '@/lib/status'
import type { AssetRow } from '@/composables/useServers'

// The lifecycle menu for one server row. Which actions show is gated by both the
// server's status and the user's capabilities — the same rules the API enforces
// in central/api/servers.py, so we never offer a button that would 403. The component
// is presentational: it emits the chosen verb; the page owns the calls.
const props = defineProps<{
  server: AssetRow
  canOpen: boolean
  canPower: boolean
  canTerminate: boolean
  busy?: boolean
  opening?: boolean
  /** A Server Migration is scheduled for this server — offer to call it off. */
  scheduledMigration?: boolean
}>()

const emit = defineEmits<{
  open: [server: AssetRow]
  start: [server: AssetRow]
  stop: [server: AssetRow]
  changePlan: [server: AssetRow]
  cancelMigration: [server: AssetRow]
  terminate: [server: AssetRow]
}>()

interface ActionItem {
  label: string
  icon: string
  theme?: 'red'
  disabled?: boolean
  onClick: () => void
}

const options = computed(() => {
  const items: ActionItem[] = []
  // Mid-resize the VM is power-cycling in the background: power + resize actions are
  // blocked (the API rejects them too) until the reshape job clears the flag.
  const resizing = isResizing(props.server)
  const migrating = isMigrating(props.server)
  const inFlight = resizing || migrating
  if (props.canOpen)
    items.push({
      label: 'Open',
      icon: 'lucide-external-link',
      disabled: inFlight || props.server.status !== 'Running' || !props.server.gateway_url,
      onClick: () => emit('open', props.server),
    })
  if (props.canPower && canStart(props.server.status))
    items.push({ label: 'Start', icon: 'lucide-play', disabled: inFlight, onClick: () => emit('start', props.server) })
  if (props.canPower && canStop(props.server.status))
    items.push({ label: 'Stop', icon: 'lucide-square', disabled: inFlight, onClick: () => emit('stop', props.server) })
  // Change plan: resize in place, or migrate when another region is picked —
  // one dialog for both (the FC V2 Change Plan flow).
  if (props.canPower && !isTerminated(props.server.status))
    items.push({
      label: 'Change plan',
      icon: 'lucide-arrow-right-left',
      disabled: resizing || migrating,
      onClick: () => emit('changePlan', props.server),
    })
  if (props.scheduledMigration)
    items.push({
      label: 'Cancel scheduled migration',
      icon: 'lucide-calendar-x',
      onClick: () => emit('cancelMigration', props.server),
    })
  if (props.canTerminate && !isTerminated(props.server.status))
    items.push({
      label: 'Terminate',
      icon: 'lucide-trash-2',
      theme: 'red',
      onClick: () => emit('terminate', props.server),
    })
  return items
})
</script>

<template>
  <Dropdown v-if="options.length" :options="options" placement="right">
    <template #trigger>
      <Button
        variant="ghost"
        icon="lucide-ellipsis-vertical"
        :loading="busy || opening"
        aria-label="Server actions"
      />
    </template>
  </Dropdown>
</template>
