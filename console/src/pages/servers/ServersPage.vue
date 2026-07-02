<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import ServerListView from '@/components/servers/ServerListView.vue'
import TerminateDialog from '@/components/servers/TerminateDialog.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import { useServers } from '@/composables/useServers'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import type { AssetRow } from '@/composables/useServers'

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
const { activeTeam, loading: sessionLoading } = useSession()
const createTeamOpen = ref(false)
const hasNoTeam = computed(() => !sessionLoading.value && !activeTeam.value)

// Terminate confirmation — the only destructive, irreversible action.
const pendingTerminate = ref<AssetRow | null>(null)
async function confirmTerminate(server: AssetRow) {
  pendingTerminate.value = null
  await terminate(server)
}

// Resize a server (preset or custom) — the backend power-cycles the VM as needed, so
// this is one action with no separate stop step.
const pendingResize = ref<AssetRow | null>(null)
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Servers" subtitle="Your team's servers across every region.">
      <template #actions>
        <Button
v-if="activeTeam" label="Refresh" icon-left="lucide-refresh-cw" :loading="refreshing"
          @click="refreshAssets" />
        <Button v-if="activeTeam && canCreateServer"
          variant="solid"
          label="New server"
          icon-left="lucide-plus"
          @click="$router.push('/servers/new')"
        />
      </template>
    </PageHeader>

    <div class="list-page-body space-y-4 py-5">
      <EmptyState
        v-if="hasNoTeam"
        icon="lucide-users"
        title="No team yet"
        description="Create a team before provisioning servers. The team becomes the owner boundary for permissions, billing, and Atlas resources."
      >
        <template #action>
          <Button variant="solid" label="Create team" icon-left="lucide-plus" @click="createTeamOpen = true" />
        </template>
      </EmptyState>

      <template v-else>
        <p v-if="stale.length" class="rounded-md bg-surface-amber-1 px-3 py-2 text-p-sm text-ink-amber-7">
          Showing last-known data — couldn't reach: {{ stale.join(', ') }}
        </p>

        <ServerListView v-model:query="query" :servers="servers" :total-rows="totalRows" :count-loading="countLoading"
          :loading="sessionLoading || loading" :error="error" :can-create="canCreateServer" :can-power="canPowerServer"
          :can-terminate="canTerminateServer" :can-open="canOpenServer" :busy="busy" :opening="opening" @retry="reload"
          @create="$router.push('/servers/new')" @start="start" @stop="stop" @resize="pendingResize = $event"
          @terminate="pendingTerminate = $event" @open="open" />
      </template>
    </div>

    <TerminateDialog
      v-model:server="pendingTerminate"
      :loading="busy === pendingTerminate?.resource_id"
      @confirm="confirmTerminate"
    />

    <ResizeServerDialog v-model:server="pendingResize" @resized="reload" />
    <CreateTeamDialog v-model:open="createTeamOpen" />
  </div>
</template>
