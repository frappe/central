<script setup lang="ts">
import { Switch } from 'frappe-ui'
import { features } from '@/lib/features'

interface Props {
	/** The monthly price of a public IPv4 in the chosen region, or null when it has none. */
	ipv4PriceLabel: string | null
}

defineProps<Props>()
const hasPublicIpv4 = defineModel<boolean>('hasPublicIpv4', { required: true })
const hasPublicIpv6 = defineModel<boolean>('hasPublicIpv6', { required: true })
const isFirewallEnabled = defineModel<boolean>('isFirewallEnabled', {
	required: true,
})
</script>

<template>
	<div
		class="divide-y divide-outline-gray-2 rounded-6 border border-outline-gray-2"
	>
		<Switch
			v-if="features.publicIpv4"
			v-model="hasPublicIpv4"
			:disabled="!ipv4PriceLabel"
			class="px-4 py-3"
		>
			<template #label>
				<span class="block text-base-medium text-ink-gray-8">
					Public IPv4 address
					<span v-if="ipv4PriceLabel" class="text-ink-gray-5">
						· {{ ipv4PriceLabel }}
					</span>
				</span>
				<span class="mt-1 block text-p-sm text-ink-gray-5">
					{{ ipv4PriceLabel
							? 'For visitors and services that only use IPv4. You can attach or detach it later.'
							: 'Not available in this region yet.' }}
				</span>
			</template>
		</Switch>
		<Switch
			v-if="features.publicIpv6"
			v-model="hasPublicIpv6"
			class="px-4 py-3"
		>
			<template #label>
				<span class="block text-base-medium text-ink-gray-8">
					Public IPv6 address · Free
				</span>
				<span class="mt-1 block text-p-sm text-ink-gray-5">
					Anyone on the internet can reach this server at its IPv6 address.
				</span>
			</template>
		</Switch>
		<Switch
			v-if="features.firewall"
			v-model="isFirewallEnabled"
			class="px-4 py-3"
		>
			<template #label>
				<span class="block text-base-medium text-ink-gray-8">
					Enable firewall
				</span>
				<span class="mt-1 block text-p-sm text-ink-gray-5">
					Allow only SSH, HTTP, and HTTPS from the internet. You can change the
					rules later in Networking.
				</span>
			</template>
		</Switch>
	</div>
</template>
