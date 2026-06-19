import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import type { Region } from '@/types'

// Regions a team can place servers in — the Active Atlas Instances
// (central.atlas.list_instances). Used by the New Server flow's region picker.

const instances = useCall<Region[]>({
  url: method(API.listInstances),
})

export function useRegions() {
  return {
    regions: computed<Region[]>(() => instances.data ?? []),
    loading: computed(() => instances.loading),
    reload: () => instances.reload(),
  }
}
