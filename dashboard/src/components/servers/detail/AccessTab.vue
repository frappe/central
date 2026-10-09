<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import { openSettings } from '@/composables/useSettings'
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
const sshKeys = computed(() => props.overview.server.ssh_keys)

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
				<div
					class="flex items-center justify-between gap-3 rounded-4 bg-surface-gray-2 py-1 pl-3 pr-1"
				>
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

		<SettingsSection title="SSH Keys">
			<template #actions>
				<Button label="Manage keys" @click="openSettings('ssh-keys')" />
			</template>

			<ul v-if="sshKeys.length" class="divide-y divide-outline-gray-1">
				<li
					v-for="key in sshKeys"
					:key="key.fingerprint"
					class="space-y-1 py-2.5 first:pt-0 last:pb-0"
				>
					<p class="truncate text-base text-ink-gray-8">{{ key.title }}</p>
					<p class="truncate font-mono text-sm text-ink-gray-5">
						{{ key.fingerprint }}
					</p>
				</li>
			</ul>

			<p v-else class="text-p-sm text-ink-gray-5">
				This server was created without a team key. Use the web console to sign
				in.
			</p>
		</SettingsSection>
	</div>
</template>
