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
const email = computed(() => profile.data?.email || '')

const streetLines = computed(() => {
	const p = profile.data

	if (!p) return []

	return [
		[p.address_line1, p.address_line2].filter(Boolean).join(', '),
		[p.city, p.state, p.pincode].filter(Boolean).join(' '),
	].filter((line): line is string => Boolean(line))
})

const country = computed(() => profile.data?.country || '')
const gstin = computed(() => profile.data?.gstin || '')
const isIndia = computed(() => country.value === 'India')
const gstStatus = computed(() => profile.data?.gst_status || '')
</script>

<template>
	<BillingCard title="Billing details" flat>
		<template v-if="canManageBilling" #action>
			<Button size="sm" label="Edit" @click="$emit('edit')" />
		</template>

		<LoadingText v-if="loading" :lines="4" />

		<div
			v-else
			class="grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-p-sm"
		>
			<span class="text-ink-gray-5">Email</span>
			<div class="flex min-w-0 items-center gap-1.5">
				<template v-if="email">
					<span class="truncate text-ink-gray-8">{{ email }}</span>
					<CopyButton class="-my-1" :text="email" />
				</template>
				<span v-else class="text-ink-gray-5">Not set</span>
			</div>

			<span class="text-ink-gray-5">Address</span>
			<div class="text-ink-gray-8">
				<template v-if="streetLines.length">
					<span v-for="line in streetLines" :key="line" class="block">
						{{ line }}
					</span>
				</template>
				<span v-else class="text-ink-gray-5">Not set</span>
			</div>

			<span class="text-ink-gray-5">Tax region</span>
			<div :class="country ? 'text-ink-gray-8' : 'text-ink-gray-5'">
				{{ country || 'Not set' }}
			</div>

			<template v-if="isIndia">
				<span class="text-ink-gray-5">GSTIN</span>
				<div class="flex items-center gap-2">
					<template v-if="gstin">
						<span class="font-mono text-ink-gray-8">{{ gstin }}</span>
						<Badge
							v-if="gstStatus"
							:label="gstStatus"
							:theme="gstStatus === 'Active' ? 'green' : 'red'"
						/>
					</template>
					<template v-else>
						<Button
							v-if="canManageBilling"
							size="xs"
							label="Add GSTIN"
							@click="$emit('edit')"
						/>
						<span class="text-ink-gray-5">
							{{ canManageBilling ? '· needed for tax credit' : 'Not set' }}
						</span>
					</template>
				</div>
			</template>
		</div>
	</BillingCard>
</template>
