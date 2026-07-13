<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { money } from '@/lib/format'
import { successToast, errorToast } from '@/lib/toast'

// Subscribe the team to a team-level metered service, or switch it onto a different
// plan in the same family (an upgrade). Controlled by the page via v-model:open; the
// available plans + currency come from the parent's already-loaded read, so the
// dialog stays a thin form over `subscribeMeteredService`.
export interface ServicePlanOption {
  plan: string
  title: string
  billing_type: string
  settlement_mode: string
  unit: string | null
  allowance: number
  rate: number | null
  // Clusters (Atlas Instance regions) that carry their own rate. Empty when the
  // service is globally priced — the cluster picker is hidden in that case.
  priced_clusters: string[]
}

const props = defineProps<{
  open: boolean
  plans: ServicePlanOption[]
  currency: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  subscribed: []
}>()

const open = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

const plan = ref('')
const cluster = ref('')

// Reset the selection each time the dialog opens, defaulting to the first plan.
watch(open, (isOpen) => {
  if (isOpen) plan.value = props.plans[0]?.plan ?? ''
})

const options = computed(() =>
  props.plans.map((p) => ({ label: planLabel(p), value: p.plan })),
)

const selectedPlan = computed(() => props.plans.find((p) => p.plan === plan.value))

// A service is priced per cluster only when it has cluster-specific rates. When it
// does, the team must pick one of those clusters; otherwise the field is hidden and
// the subscription is globally priced.
const clusterOptions = computed(() =>
  (selectedPlan.value?.priced_clusters ?? []).map((c) => ({ label: c, value: c })),
)
const showCluster = computed(() => clusterOptions.value.length > 0)

// Keep the cluster valid for the chosen plan: default to its first priced cluster
// when the picker is shown, and clear it for a globally-priced plan.
watch(
  [plan, () => props.plans],
  () => {
    const priced = selectedPlan.value?.priced_clusters ?? []
    cluster.value = priced.includes(cluster.value) ? cluster.value : (priced[0] ?? '')
  },
  { immediate: true },
)

function planLabel(p: ServicePlanOption): string {
  const price =
    p.rate == null
      ? 'unpriced'
      : `${money(p.rate, props.currency, { trimTrailingZeros: true })}/${p.unit || 'unit'}`
  const included = p.allowance ? `, ${p.allowance.toLocaleString()} ${p.unit || 'unit'} included` : ''
  return `${p.title} — ${price}${included}`
}

const { activeTeam } = useSession()

const subscribe = useCall<
  { service_subject: string; upgraded: boolean },
  { team: string | null; plan: string; cluster: string | undefined }
>({
  url: method(API.subscribeMeteredService),
  method: 'POST',
  immediate: false,
})

async function onSubmit(): Promise<void> {
  if (!plan.value) return
  try {
    await subscribe.submit({
      team: activeTeam.value,
      plan: plan.value,
      cluster: cluster.value || undefined,
    })
    successToast(subscribe.data?.upgraded ? 'Service plan updated.' : 'Service subscribed.')
    emit('subscribed')
    open.value = false
  } catch (e) {
    errorToast(e)
  }
}

const actions = computed(() => [
  {
    label: 'Subscribe',
    variant: 'solid' as const,
    loading: subscribe.loading,
    disabled: !plan.value || (showCluster.value && !cluster.value),
    onClick: onSubmit,
  },
])
</script>

<template>
  <Dialog v-model="open" title="Subscribe to a service" :actions="actions">
    <template #body-content>
      <div class="space-y-4">
        <FormControl
          type="select"
          v-model="plan"
          :options="options"
          label="Service plan"
          description="Metered services bill per unit of usage; a bundle includes an allowance."
        />
        <FormControl
          v-if="showCluster"
          type="select"
          v-model="cluster"
          :options="clusterOptions"
          label="Cluster"
          description="This service is priced per cluster — pick where you'll consume it."
        />
      </div>
    </template>
  </Dialog>
</template>
