<script setup lang="ts">
import { Checkbox } from 'frappe-ui'

const hasPublicIpv6 = defineModel<boolean>('hasPublicIpv6', { required: true })
const isFirewallEnabled = defineModel<boolean>('isFirewallEnabled', {
	required: true,
})
</script>

<template>
	<fieldset class="space-y-3">
		<legend class="mb-2 text-sm text-ink-gray-5">Network</legend>
		<div class="space-y-1">
			<Checkbox v-model="hasPublicIpv6" label="Public IPv6 address" />
			<p class="pl-6 text-p-sm text-ink-gray-5">
				Anyone on the internet can reach this server at its IPv6 address.
			</p>
		</div>
		<div class="space-y-1">
			<Checkbox v-model="isFirewallEnabled" label="Enable firewall" />
			<p class="pl-6 text-p-sm text-ink-gray-5">
				Allow only SSH, HTTP, and HTTPS from the internet.
			</p>
		</div>
	</fieldset>
</template>
