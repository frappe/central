<script setup lang="ts">
import { Button, Dialog, useCall } from 'frappe-ui'
// "Action Required" banner — shown when an INR e-mandate team's bill crosses the
// ₹15,000 silent-debit limit and the customer must choose how to keep paying
// (ADR 0005 / payments-inr.md). Calm, not alarming: services keep running; this
// is an invitation to decide. Backend feed: get_collection_status.
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import Alert from '@/components/common/Alert.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { CollectionStatus } from '@/types/billing'

const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const status = useCall<CollectionStatus, { team: string }>({
	url: method(API.collectionStatus),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => status.reload())

const s = computed(() => status.data)
const show = computed(() => !!s.value?.action_required)
const currency = computed(() => s.value?.currency || 'INR')

const choosing = ref(false)
const chosen = ref<string | null>(null) // 'Manual Checkout' | 'Prepaid'

const setMode = useCall<unknown, { team: string; mode: string }>({
	url: method(API.setCollectionMode),
	method: 'POST',
	immediate: false,
	onError: (e: unknown) => errorToast(e, 'Could not update how you pay.'),
})

async function choose(): Promise<void> {
	if (!chosen.value) return
	await setMode.submit({ team: activeTeam.value!, mode: chosen.value })
	successToast(
		chosen.value === 'Prepaid'
			? 'Switched to prepaid wallet. Add credits to cover your usage.'
			: "You'll now pay each invoice yourself.",
	)
	choosing.value = false
	chosen.value = null
	status.reload()
}

const options = [
	{
		key: 'Manual Checkout',
		icon: 'lucide-receipt',
		title: 'Pay each invoice',
		blurb: 'We email you each bill; you pay in a few taps (any amount).',
		fit: 'Best if your usage varies a lot month to month.',
	},
	{
		key: 'Prepaid',
		icon: 'lucide-wallet',
		title: 'Prepaid wallet',
		blurb: 'Add credits up front; your usage draws them down.',
		fit: 'Best for hands-off, predictable spending.',
	},
]
</script>

<template>
	<Alert
		v-if="show && s"
		theme="yellow"
		title="Action required — choose how to keep paying"
		:action="canManageBilling ? { label: 'Choose how to pay', onClick: () => (choosing = true) } : undefined"
	>
		<template #description>
			Your usage is trending to
			<span class="font-medium">{{ money(s.projected_total, currency) }}</span>
			this month, above the
			<span class="font-medium">{{ money(s.threshold, currency) }}</span>
			limit for automatic payments. Your services keep running.
		</template>
	</Alert>

	<Dialog
		v-model:open="choosing"
		title="How would you like to pay going forward?"
	>
		<template #default>
			<div class="grid gap-3 sm:grid-cols-2">
				<button
					v-for="o in options"
					:key="o.key"
					type="button"
					class="flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors"
					:class="
            chosen === o.key
              ? 'border-outline-gray-4 bg-surface-gray-2'
              : 'border-outline-gray-2 hover:border-outline-gray-3'
          "
					@click="chosen = o.key"
				>
					<span
						:class="o.icon"
						class="size-5 text-ink-gray-7"
						aria-hidden="true"
					/>
					<span class="text-base font-medium text-ink-gray-9"
						>{{ o.title }}</span
					>
					<span class="text-p-sm text-ink-gray-6">{{ o.blurb }}</span>
					<span class="mt-auto text-p-sm text-ink-gray-5">{{ o.fit }}</span>
				</button>
			</div>
			<p class="mt-3 text-p-sm text-ink-gray-5">
				You can switch anytime in Billing settings.
			</p>
		</template>
		<template #actions>
			<Button
				variant="solid"
				label="Confirm"
				class="w-full"
				:loading="setMode.loading"
				:disabled="!chosen"
				@click="choose"
			/>
		</template>
	</Dialog>
</template>
