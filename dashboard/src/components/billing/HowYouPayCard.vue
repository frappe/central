<script setup lang="ts">
import { Button, Skeleton, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import CollectionModeDialog from '@/components/billing/CollectionModeDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { limitText } from '@/lib/collectionText'
import { __ } from '@/lib/translate'
import type { CollectionStatus } from '@/types/billing'

const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()
const { methods } = useBillingOverview()

const status = useCall<CollectionStatus, { team: string }>({
	url: method(API.collectionStatus),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => status.reload())
// The method charged first follows the order on the Payment methods card, so
// refetch only when the first method changes, not on the first load.
watch(
	() => (methods.data ? (methods.data[0]?.name ?? null) : undefined),
	(_first, previous) => {
		if (previous !== undefined) status.reload()
	},
)

const s = computed(() => status.data)
// Change shows only when there is another way to pay to pick.
const canChange = computed(
	() =>
		canManageBilling.value &&
		!!s.value &&
		(s.value.manual_offered || s.value.choice !== 'Automatic'),
)
const choosing = ref(false)

const heading = computed(() => {
	if (s.value?.action_required) return __('Automatic payments are paused')
	if (s.value?.choice === 'Manual') return __('You pay each invoice yourself')
	return __('You pay automatically')
})

const sentence = computed(() => {
	const st = s.value
	if (!st) return ''
	if (st.action_required)
		return __(
			'Your wallet pays first. Choose how to pay the rest. Your services keep running.',
		)
	if (st.choice === 'Manual')
		return __(
			'Your wallet pays first. We email you each invoice, and you pay the rest yourself.',
		)
	if (!st.charged_method)
		return __(
			'Your wallet pays first. No card or UPI is saved, so you pay the rest of each invoice yourself.',
		)
	return __('Your wallet pays first. When it is short, we charge {0}.', [
		st.charged_method,
	])
})

// The INR limit only matters when a card or UPI is charged automatically.
const limitLine = computed(() => {
	const st = s.value
	if (!st || st.choice !== 'Automatic' || !st.charged_method) return ''
	if (st.threshold == null) return ''
	return __('Your card or UPI pays only amounts up to {0}.', [
		limitText(st, st.threshold),
	])
})
</script>

<template>
	<BillingCard :title="__('How you pay')" flat>
		<template #action>
			<Button
				v-if="canChange"
				size="sm"
				:label="s?.action_required ? __('Choose how to pay') : __('Change')"
				@click="choosing = true"
			/>
		</template>

		<p v-if="status.error && !s" class="text-p-sm text-ink-gray-6">
			{{ __("Couldn't load how you pay. Reload the page to try again.") }}
		</p>
		<Skeleton v-else-if="!s" class="h-16 rounded-5" />
		<div
			v-else
			class="flex flex-col gap-1 rounded-5 border border-outline-gray-1 p-3"
		>
			<div class="text-base text-ink-gray-9">{{ heading }}</div>
			<p class="text-p-sm text-ink-gray-6">{{ sentence }}</p>
			<p v-if="limitLine" class="text-p-sm text-ink-gray-5">{{ limitLine }}</p>
		</div>
	</BillingCard>

	<CollectionModeDialog
		v-if="s"
		v-model:open="choosing"
		:status="s"
		@changed="status.reload()"
	/>
</template>
