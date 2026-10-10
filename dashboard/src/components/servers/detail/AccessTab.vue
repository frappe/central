<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { openSettings } from '@/composables/useSettings'
import type { ServerOverview } from '@/types/servers'

interface Props {
	overview: ServerOverview
}

const props = defineProps<Props>()

const sshCommand = computed(() => props.overview.server.ssh_command)
const sshKeys = computed(() => props.overview.server.ssh_keys)
</script>

<template>
	<div class="divide-y divide-outline-gray-1">
		<SettingsSection
			title="SSH"
			:description="
				sshCommand
					? 'Sign in with one of the keys below. Add -i path/to/key if your key is not the default.'
					: 'The command appears once the server has a public address.'
			"
		>
			<div
				v-if="sshCommand"
				class="flex items-center justify-between gap-3 rounded-4 bg-surface-gray-2 py-1 pl-3 pr-1"
			>
				<code class="min-w-0 truncate font-mono text-sm text-ink-gray-8">
					{{ sshCommand }}
				</code>

				<CopyButton :text="sshCommand" />
			</div>
		</SettingsSection>

		<SettingsSection
			title="SSH keys"
			:description="
				sshKeys.length
					? 'Keys that can sign in to this server.'
					: 'This server was created without a team key. Use the web console in Actions to sign in.'
			"
		>
			<template #actions>
				<Button label="Manage keys" @click="openSettings('ssh-keys')" />
			</template>

			<ul
				v-if="sshKeys.length"
				class="divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-1"
			>
				<li
					v-for="key in sshKeys"
					:key="key.fingerprint"
					class="space-y-1 px-3 py-2.5"
				>
					<p class="truncate text-base text-ink-gray-8">{{ key.title }}</p>
					<p class="truncate font-mono text-sm text-ink-gray-5">
						{{ key.fingerprint }}
					</p>
				</li>
			</ul>
		</SettingsSection>
	</div>
</template>
