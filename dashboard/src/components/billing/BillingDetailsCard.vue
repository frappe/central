<script setup lang="ts">
import { Badge, Button, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import CopyButton from '@/components/common/CopyButton.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'

defineEmits<{ edit: [] }>()

const { profile } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const loading = computed(() => profile.loading && !profile.data)
const data = computed(() => profile.data)

// The block reads as the "Billed to" part of an invoice: who, then where.
const addressLines = computed(() => {
	const p = data.value
	if (!p) return []

	const region = [p.state, p.pincode].filter(Boolean).join(' ')
	return [
		[p.address_line1, p.address_line2].filter(Boolean).join(', '),
		[p.city, region].filter(Boolean).join(', '),
		p.country,
	].filter((line): line is string => Boolean(line))
})

const isIndia = computed(() => data.value?.country === 'India')
const gstStatus = computed(() => data.value?.gst_status || '')
</script>

<template>
	<BillingCard title="Billing details" flat>
		<template v-if="canManageBilling" #action>
			<Button size="sm" label="Edit" @click="$emit('edit')" />
		</template>

		<LoadingText v-if="loading" :lines="4" />

		<div
			v-else-if="data"
			class="grid gap-x-8 gap-y-5 rounded-5 border border-outline-gray-1 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"
		>
			<div class="min-w-0">
				<p class="text-sm text-ink-gray-5">Billed to</p>
				<p class="mt-1.5 text-base-medium text-ink-gray-9">
					{{ data.legal_name || 'No legal name' }}
				</p>
				<p
					v-for="line in addressLines"
					:key="line"
					class="text-p-sm text-ink-gray-7"
				>
					{{ line }}
				</p>
			</div>

			<dl
				class="grid min-w-0 grid-cols-[6rem_minmax(0,1fr)] content-start gap-x-3 gap-y-2 text-p-sm"
			>
				<dt class="text-ink-gray-5">Email</dt>
				<dd class="flex min-w-0 items-center gap-1.5">
					<template v-if="data.email">
						<span class="truncate text-ink-gray-8">{{ data.email }}</span>
						<CopyButton class="-my-1" :text="data.email" />
					</template>
					<span v-else class="text-ink-gray-5">Not set</span>
				</dd>

				<dt class="text-ink-gray-5">Phone</dt>
				<dd :class="data.phone ? 'text-ink-gray-8' : 'text-ink-gray-5'">
					{{ data.phone || 'Not set' }}
				</dd>

				<dt class="text-ink-gray-5">Currency</dt>
				<dd class="text-ink-gray-8">{{ data.currency || 'Not set' }}</dd>

				<template v-if="isIndia">
					<dt class="text-ink-gray-5">GSTIN</dt>
					<dd class="flex min-w-0 flex-wrap items-center gap-2">
						<template v-if="data.gstin">
							<span class="font-mono text-ink-gray-8">{{ data.gstin }}</span>
							<Badge
								v-if="gstStatus"
								:label="gstStatus"
								:theme="gstStatus === 'Active' ? 'green' : 'red'"
							/>
						</template>
						<span v-else class="text-ink-gray-5">
							Not set. Add it to claim tax credit.
						</span>
					</dd>
				</template>
			</dl>
		</div>
	</BillingCard>
</template>
