import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { createListViewQuery } from '@/components/common/list-view'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useFrappeList } from '@/composables/common/useFrappeList'
import { successToast, errorToast, getErrorMessage } from '@/lib/toast'
import type { RefreshResponse } from '@/types/api'
import type { Asset } from '@/types/Central/Asset'

type BenchLinkResponse = {
  url: string
}

export type AssetRow = Pick<
  Asset,
  | 'name'
  | 'resource_id'
  | 'title'
  | 'cluster'
  | 'status'
  | 'vcpus'
  | 'memory_megabytes'
  | 'disk_gigabytes'
  | 'ipv6_address'
  | 'public_ipv4'
  | 'gateway_url'
  | 'last_synced_at'
>

// The team's servers, read from the Asset DocType through Frappe reportview, plus
// the lifecycle command path. The mirror is kept fresh by Atlas's event push +
// the reconcile pull, so a command's effect lands on the next refresh, not
// synchronously — hence every action `reload()`s after it fires.

const { activeTeam } = useSession()

// Param shapes for the lifecycle/SSO methods (central/api/servers.py, central/sso.py).
type TeamParams = { team: string }
type CommandParams = { team: string; resource_id: string }

const query = ref(
  createListViewQuery({
    pageSize: 20,
    sort: { key: 'cluster', direction: 'asc' },
  }),
)

const registry = useFrappeList<AssetRow>({
  doctype: 'Asset',
  fields: [
    'name',
    'resource_id',
    'title',
    'cluster',
    'status',
    'vcpus',
    'memory_megabytes',
    'disk_gigabytes',
    'ipv6_address',
    'public_ipv4',
    'gateway_url',
    'last_synced_at',
  ],
  query,
  filters: () => [['team', '=', activeTeam.value]],
  searchFields: ['title', 'resource_id', 'cluster', 'status'],
  sortableFields: ['title', 'cluster', 'status', 'resource_id'],
  defaultOrderBy: 'cluster asc, resource_id asc',
})

whenTeamReady(() => registry.reload())

// Re-pulls the mirror from every Active Atlas, then re-reads it.
const refresh = useCall<RefreshResponse, TeamParams>({
  url: method(API.refreshAssets),
  method: 'POST',
  immediate: false,
})

type CreateParams = {
  team: string
  region: string
  title: string
  plan: string
  vcpus: number
  memory_megabytes: number
  disk_gigabytes: number
  cpu_max_cores?: number
}
const createCall = useCall<{ resource_id: string }, CreateParams>({
  url: method(API.createServer),
  method: 'POST',
  immediate: false,
})

// Design-your-own (composed) provision: the server is built from a composition
// (qty per resource) + its optimisation profile, billed à la carte (#80/#84).
type ComposedInclude = { resource_type: string; quantity: number; unit: string }
type CreateComposedParams = {
  team: string
  region: string
  title: string
  includes: ComposedInclude[]
  sub_category: string
}
const createComposedCall = useCall<{ resource_id: string }, CreateComposedParams>({
  url: method(API.createComposedServer),
  method: 'POST',
  immediate: false,
})

const startCall = useCall<unknown, CommandParams>({ url: method(API.startServer), method: 'POST', immediate: false })
const stopCall = useCall<unknown, CommandParams>({ url: method(API.stopServer), method: 'POST', immediate: false })
const terminateCall = useCall<unknown, CommandParams>({ url: method(API.terminateServer), method: 'POST', immediate: false })
const benchLink = useCall<BenchLinkResponse, { asset: string }>({ url: method(API.getBenchLink), immediate: false })

// One row mutates at a time; `busy` holds its resource_id so the row can show a
// spinner and gate its own menu. `opening` does the same for open-in-bench.
const busy = ref<string>('')
const opening = ref<string>('')

type Verb = 'Start' | 'Stop' | 'Terminate'

async function runCommand(
  call: typeof startCall,
  server: AssetRow,
  verb: Verb,
): Promise<void> {
  busy.value = server.resource_id
  try {
    await call.submit({ team: activeTeam.value!, resource_id: server.resource_id })
    successToast(`${verb} requested for ${server.title || server.resource_id}.`)
    registry.reload()
  } catch (e) {
    errorToast(e)
  } finally {
    busy.value = ''
  }
}

export function useServers() {
  registry.listenForUpdates()

  async function refreshAssets(): Promise<void> {
    try {
      await refresh.submit({ team: activeTeam.value! })
      registry.reload()
    } catch (e) {
      errorToast(e)
    }
  }

  function start(server: AssetRow) {
    return runCommand(startCall, server, 'Start')
  }
  function stop(server: AssetRow) {
    return runCommand(stopCall, server, 'Stop')
  }
  function terminate(server: AssetRow) {
    return runCommand(terminateCall, server, 'Terminate')
  }

  // Open the VM's bench via a scoped SSO assertion. The tab is opened
  // synchronously inside the click so it isn't popup-blocked, then pointed at the
  // minted URL once it resolves.
  async function open(server: AssetRow): Promise<void> {
    opening.value = server.resource_id
    const tab = window.open('', '_blank')
    try {
      await benchLink.submit({ asset: server.resource_id })
      const url = benchLink.data?.url
      if (url && tab) tab.location.href = url
      else if (url) window.location.href = url
      else tab?.close()
    } catch (e) {
      tab?.close()
      errorToast(e)
    } finally {
      opening.value = ''
    }
  }

  // Provision a new server in a region. Returns the new resource_id on success
  // (so the caller can navigate), throws on failure (so it can surface the error).
  async function create(params: Omit<CreateParams, 'team'>): Promise<string> {
    await createCall.submit({ team: activeTeam.value!, ...params })
    // useCall surfaces HTTP failures on `.error` rather than throwing — surface
    // it and re-throw so the page keeps the user on the form.
    if (createCall.error) {
      errorToast(createCall.error)
      throw createCall.error
    }
    successToast(`Creating ${params.title} in ${params.region}.`)
    registry.reload()
    return createCall.data?.resource_id ?? ''
  }

  // Provision a design-your-own (composed) server. Same contract as create().
  async function createComposed(params: Omit<CreateComposedParams, 'team'>): Promise<string> {
    await createComposedCall.submit({ team: activeTeam.value!, ...params })
    if (createComposedCall.error) {
      errorToast(createComposedCall.error)
      throw createComposedCall.error
    }
    successToast(`Creating ${params.title} in ${params.region}.`)
    registry.reload()
    return createComposedCall.data?.resource_id ?? ''
  }

  return {
    servers: registry.rows,
    totalRows: registry.totalRows,
    countLoading: registry.countLoading,
    query,
    loading: registry.loading,
    error: computed(() =>
      registry.error.value
        ? getErrorMessage(registry.error.value, "Couldn't load servers.")
        : null,
    ),
    refreshing: computed(() => refresh.loading),
    creating: computed(() => createCall.loading),
    creatingComposed: computed(() => createComposedCall.loading),
    // Atlas instances that couldn't be reached on the last refresh — their rows
    // show last-known data.
    stale: computed<string[]>(() => refresh.data?.stale ?? []),
    busy,
    opening,
    reload: () => registry.reload(),
    refreshAssets,
    create,
    createComposed,
    start,
    stop,
    terminate,
    open,
  }
}
