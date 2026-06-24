<script setup lang="ts">
import { ref } from 'vue'
import { Button } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import ServerListView from '@/components/servers/ServerListView.vue'
import TerminateDialog from '@/components/servers/TerminateDialog.vue'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import type { Server } from '@/types'

// The team's servers, mirrored from Atlas. A standard list with the lifecycle
// actions Central actually implements — start/stop (server:power), terminate
// (server:terminate), and Open, which mints a scoped SSO link into the VM's
// bench (server:open). Terminate routes through a destructive confirm.
const {
  servers,
  totalRows,
  countLoading,
  query,
  loading,
  error,
  refreshing,
  stale,
  busy,
  opening,
  reload,
  refreshAssets,
  start,
  stop,
  terminate,
  open,
} = useServers()

const { canPowerServer, canTerminateServer, canOpenServer, canCreateServer } = useCapabilities()

// Terminate confirmation — the only destructive, irreversible action.
const pendingTerminate = ref<Server | null>(null)
async function confirmTerminate(server: Server) {
  pendingTerminate.value = null
  await terminate(server)
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Servers" subtitle="Your team's servers across every region.">
      <template #actions>
        <Button label="Refresh" icon-left="lucide-refresh-cw" :loading="refreshing" @click="refreshAssets" />
        <Button
          v-if="canCreateServer"
          variant="solid"
          label="New server"
          icon-left="lucide-plus"
          @click="$router.push('/servers/new')"
        />
      </template>
    </PageHeader>

    <div class="list-page-body space-y-4 py-5">
      <p
        v-if="stale.length"
        class="rounded-md bg-surface-amber-1 px-3 py-2 text-p-sm text-ink-amber-3"
      >
        Showing last-known data — couldn't reach: {{ stale.join(', ') }}
      </p>

      <ServerListView
        v-model:query="query"
        :servers="servers"
        :total-rows="totalRows"
        :count-loading="countLoading"
        :loading="loading"
        :error="error"
        :can-create="canCreateServer"
        :can-power="canPowerServer"
        :can-terminate="canTerminateServer"
        :can-open="canOpenServer"
        :busy="busy"
        :opening="opening"
        @retry="reload"
        @create="$router.push('/servers/new')"
        @start="start"
        @stop="stop"
        @terminate="pendingTerminate = $event"
        @open="open"
      />
    </div>

    <TerminateDialog
      v-model:server="pendingTerminate"
      :loading="busy === pendingTerminate?.resource_id"
      @confirm="confirmTerminate"
    />
  </div>
</template>
