import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { errorToast, successToast } from '@/lib/toast'

// The team's pending Server Migrations (central.api.migrations.list_migrations):
// Scheduled ones the console badges + lets the user cancel, Running ones the map
// already shows via the Asset's migration_in_progress flag.

export interface MigrationRow {
  name: string
  asset: string
  from_cluster: string
  to_cluster: string
  pricing_mode: 'Preset' | 'Composed'
  plan: string | null
  status: 'Scheduled' | 'Running'
  scheduled_at: string | null
  started_at: string | null
}

const { activeTeam } = useSession()

const list = useCall<MigrationRow[], { team: string }>({
  url: method(API.listMigrations),
  params: teamParams,
  immediate: false,
})

whenTeamReady(() => list.reload())

const cancelCall = useCall<{ migration: string }, { team: string; migration: string }>({
  url: method(API.cancelMigration),
  method: 'POST',
  immediate: false,
})

export function useMigrations() {
  const migrations = computed<MigrationRow[]>(() => list.data ?? [])

  function scheduledFor(resourceId: string): MigrationRow | null {
    return migrations.value.find((m) => m.asset === resourceId && m.status === 'Scheduled') ?? null
  }

  async function cancel(migration: MigrationRow): Promise<void> {
    try {
      await cancelCall.submit({ team: activeTeam.value!, migration: migration.name })
      if (cancelCall.error) throw cancelCall.error
      successToast(`Migration to ${migration.to_cluster} cancelled.`)
      list.reload()
    } catch (e) {
      errorToast(e)
    }
  }

  return { migrations, scheduledFor, cancel, reload: () => list.reload() }
}
