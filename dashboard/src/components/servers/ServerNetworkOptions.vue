<script setup lang="ts">
import { Switch } from 'frappe-ui'

const hasPublicIpv6 = defineModel<boolean>('hasPublicIpv6', { required: true })
const isFirewallEnabled = defineModel<boolean>('isFirewallEnabled', {
	required: true,
})
</script>

<template>
	<div
		class="divide-y divide-outline-gray-2 rounded-6 border border-outline-gray-2"
	>
		<Switch v-model="hasPublicIpv6" class="px-4 py-3">
			<template #label>
				<span class="block text-base-medium text-ink-gray-8">
					Public IPv6 address
				</span>
				<span class="mt-1 block text-p-sm text-ink-gray-5">
					Anyone on the internet can reach this server at its IPv6 address.
				</span>
			</template>
		</Switch>
		<Switch v-model="isFirewallEnabled" class="px-4 py-3">
			<template #label>
				<span class="block text-base-medium text-ink-gray-8">
					Enable firewall
				</span>
				<span class="mt-1 block text-p-sm text-ink-gray-5">
					Allow only SSH, HTTP, and HTTPS from the internet.
				</span>
			</template>
		</Switch>
	</div>
</template>
