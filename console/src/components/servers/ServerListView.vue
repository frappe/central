<script setup lang="ts">
import { Button } from 'frappe-ui'
import ServerStatusBadge from '@/components/servers/ServerStatusBadge.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import { formatSpecs } from '@/lib/format'
import type { Server } from '@/types'

// Standard server list. Presentational: the page owns data + actions and passes
// capability flags down so the row only offers what the API would allow.
defineProps<{
  servers: Server[]
  canPower: boolean
  canTerminate: boolean
  canOpen: boolean
  busy: string
  opening: string
}>()

const emit = defineEmits<{
  start: [server: Server]
  stop: [server: Server]
  terminate: [server: Server]
  open: [server: Server]
}>()
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-outline-gray-2">
    <table class="w-full border-collapse text-left">
      <thead>
        <tr class="border-b border-outline-gray-2 bg-surface-gray-1 text-p-sm text-ink-gray-5">
          <th class="px-4 py-2.5 font-medium">Name</th>
          <th class="px-4 py-2.5 font-medium">Region</th>
          <th class="hidden px-4 py-2.5 font-medium sm:table-cell">Specs</th>
          <th class="px-4 py-2.5 font-medium">Status</th>
          <th class="px-4 py-2.5 text-right font-medium">Actions</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-outline-gray-1">
        <tr
          v-for="server in servers"
          :key="server.resource_id"
          class="text-base text-ink-gray-8 hover:bg-surface-gray-1"
        >
          <td class="px-4 py-3">
            <p class="font-medium text-ink-gray-9">{{ server.title || server.resource_id }}</p>
            <p class="text-p-sm text-ink-gray-5 sm:hidden">{{ formatSpecs(server) }}</p>
          </td>
          <td class="px-4 py-3 text-ink-gray-7">{{ server.cluster }}</td>
          <td class="hidden px-4 py-3 text-ink-gray-7 sm:table-cell">{{ formatSpecs(server) }}</td>
          <td class="px-4 py-3">
            <ServerStatusBadge :status="server.status" />
          </td>
          <td class="px-4 py-3">
            <div class="flex items-center justify-end gap-1">
              <Button
                v-if="canOpen"
                variant="ghost"
                label="Open"
                icon-right="lucide-external-link"
                :loading="opening === server.resource_id"
                :disabled="server.status !== 'Running' || !server.gateway_url"
                @click="emit('open', server)"
              />
              <ServerRowActions
                :server="server"
                :can-power="canPower"
                :can-terminate="canTerminate"
                :busy="busy === server.resource_id"
                @start="emit('start', $event)"
                @stop="emit('stop', $event)"
                @terminate="emit('terminate', $event)"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
