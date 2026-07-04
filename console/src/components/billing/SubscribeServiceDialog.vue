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
  if (isOpen) {
    plan.value = props.plans[0]?.plan ?? ''
    cluster.value = ''
  }
})

const options = computed(() =>
  props.plans.map((p) => ({ label: planLabel(p), value: p.plan })),
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
    disabled: !plan.value,
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
          v-model="cluster"
          label="Cluster"
          description="Optional — leave blank for a globally-priced service."
          placeholder="e.g. mumbai"
        />
      </div>
    </template>
  </Dialog>
</template>
