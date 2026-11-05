<script setup lang="ts">
import { Button } from 'frappe-ui'
import { ref } from 'vue'
import FirewallSection from '@/components/servers/firewall/FirewallSection.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { FirewallRules } from '@/lib/firewall'

const resizing = ref(false)
const enabled = ref(!new URLSearchParams(location.search).has('emptyFirewall'))
const server: VirtualMachineRow = {
	name: 'test-vm',
	resource_id: 'test-vm',
	region: 'test-region',
	title: 'Test server',
	status: 'Running',
}
const anywhere = ['0.0.0.0/0', '::/0']
const rules = ref<FirewallRules>({
	inbound: [
		{ protocol: 'tcp', ports: '22', cidrs: anywhere },
		{ protocol: 'tcp', ports: '443', cidrs: anywhere },
	],
	outbound: [{ protocol: 'any', ports: '', cidrs: anywhere }],
})

if (!enabled.value) rules.value = { inbound: [], outbound: [] }
if (new URLSearchParams(location.search).has('specificFirewall'))
	rules.value.inbound[0].cidrs = ['203.0.113.7/32']

if (new URLSearchParams(location.search).has('allTcpPorts'))
	rules.value.inbound[0].ports = ''

function removeObservedSsh(): void {
	rules.value = {
		...rules.value,
		inbound: rules.value.inbound.filter((rule) => rule.ports !== '22'),
	}
}

function refresh(): void {
	rules.value = JSON.parse(JSON.stringify(rules.value))
}
</script>
<template>
	<main style="max-width: 960px; margin: 48px auto; padding: 16px;">
		<Button label="Resize server" @click="resizing = true" />
		<Button label="Refresh observed rules" @click="refresh" />
		<Button label="Remove observed SSH" @click="removeObservedSsh" />
		<FirewallSection
			resource-id="test-vm"
			:is-enabled="enabled"
			:rules="rules"
			:can-edit="true"
			:servers="[]"
		/>
		<ResizeServerDialog v-model:open="resizing" :server="server" />
	</main>
</template>
