<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerActions } from '@/lib/capabilities'
import type { ServerOverview } from '@/types/servers'

interface Props {
	server: VirtualMachineRow
	overview: ServerOverview
	actions: ServerActions
	opening: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
	console: []
	open: []
}>()

const isUbuntu = computed(() => props.server.image_offering === 'ubuntu')
const isRunning = computed(() => props.server.status === 'Running')
const sshCommand = computed(() => props.overview.server.ssh_command)

const consoleNote = computed(() =>
	isRunning.value
		? 'A root shell in your browser. It needs no key and opens in a new window.'
		: 'Start the server to open its console.',
)
</script>

<template>
	<div class="divide-y divide-outline-gray-1">
		<SettingsSection v-if="actions.console" title="Web console">
			<template #actions>
				<Button
					icon-left="lucide-terminal"
					label="Open console"
					:disabled="!isRunning"
					:loading="opening"
					@click="emit('console')"
				/>
			</template>

			<p class="text-p-sm text-ink-gray-6">{{ consoleNote }}</p>
		</SettingsSection>

		<SettingsSection title="SSH">
			<template v-if="sshCommand">
				<div class="flex items-center gap-3">
					<code class="min-w-0 truncate font-mono text-sm text-ink-gray-8">
						{{ sshCommand }}
					</code>

					<CopyButton :text="sshCommand" />
				</div>

				<p class="text-p-sm text-ink-gray-5">
					Sign in with one of the keys below. If your key is not the default,
					add <code class="font-mono text-ink-gray-7">-i path/to/key</code>.
				</p>
			</template>

			<p v-else class="text-p-sm text-ink-gray-5">
				The command appears once the server has a public address.
			</p>
		</SettingsSection>

		<SettingsSection v-if="!isUbuntu && actions.open" title="Pilot">
			<template #actions>
				<Button
					icon-right="lucide-arrow-up-right"
					label="Open Pilot"
					:disabled="!isRunning || !server.gateway_url"
					:loading="opening"
					@click="emit('open')"
				/>
			</template>

			<p class="text-p-sm text-ink-gray-6">
				Manage benches, sites and apps on this server. You sign in with your
				Frappe Cloud account.
			</p>
		</SettingsSection>

		<SettingsSection title="SSH keys">
			<template #actions>
				<Button label="Manage keys" route="/servers/ssh-keys" />
			</template>

			<p class="text-p-sm text-ink-gray-6">
				Keys belong to the team and are added to a server when you create it.
				Add or rotate them on the SSH keys page.
			</p>
		</SettingsSection>
	</div>
</template>
