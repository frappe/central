<script setup lang="ts">
import { Button, call } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API } from '@/api/methods'
import CopyButton from '@/components/common/CopyButton.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import WireGuardSection from '@/components/servers/detail/WireGuardSection.vue'
import EditSSHKeysDialog from '@/components/servers/EditSSHKeysDialog.vue'
import SSHKeyDialog from '@/components/servers/SSHKeyDialog.vue'
import { useSession } from '@/composables/useSession'
import { useTeamSSHKeys } from '@/composables/useTeamSSHKeys'
import { ACCESS_LOCKED_REASON } from '@/lib/capabilities'
import { successToast } from '@/lib/feedback'
import type { ServerOverview } from '@/types/servers'

interface Props {
	overview: ServerOverview
	/** The viewer holds server:ssh-key, so they can change this server's keys. */
	canManageKeys: boolean
	/** The viewer holds server:network on this server. */
	canManageNetwork: boolean
	/** The server runs a free trial, so SSH waits for an upgrade. */
	isAccessLocked?: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: []; upgrade: [] }>()

const sshCommand = computed(() => props.overview.server.ssh_command)
const sshKeys = computed(() => props.overview.server.ssh_keys)
const canEditKeys = computed(
	() =>
		props.canManageKeys &&
		!props.isAccessLocked &&
		props.overview.server.status !== 'Terminated',
)
const isEditing = ref(false)
const isAdding = ref(false)

const { activeTeam } = useSession()
const { keys: teamKeys, create: createTeamKey } = useTeamSSHKeys()

// A team without keys has nothing to pick, so it starts by adding one.
function editKeys(): void {
	if (teamKeys.value.length) isEditing.value = true
	else isAdding.value = true
}

async function addToServer(title: string, publicKey: string) {
	const key = await createTeamKey(title, publicKey)
	await call(API.setServerSSHKeys, {
		team: activeTeam.value,
		resource_id: props.overview.server.resource_id,
		ssh_keys: [...sshKeys.value.map((row) => row.name), key.name],
	})
	return key
}

function changed(): void {
	successToast('SSH keys updated')
	emit('changed')
}
</script>

<template>
	<div v-if="isAccessLocked" class="divide-y divide-outline-gray-1">
		<SettingsSection title="SSH" :description="ACCESS_LOCKED_REASON">
			<template #actions>
				<Button variant="solid" label="Upgrade" @click="emit('upgrade')" />
			</template>
			<p class="text-p-sm text-ink-gray-6">
				Your free trial includes the site. SSH, the web console, Pilot and
				snapshots open when you upgrade.
			</p>
		</SettingsSection>
	</div>

	<div v-else class="divide-y divide-outline-gray-1">
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
					: 'This server has no SSH key. To get a root shell, open Actions, then Web console, then SSH session.'
			"
		>
			<template v-if="canEditKeys" #actions>
				<Button
					:label="sshKeys.length ? 'Edit keys' : 'Add keys'"
					@click="editKeys"
				/>
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

		<WireGuardSection
			v-if="overview.server.region_details.has_wireguard_gateway"
			:resource-id="overview.server.resource_id"
			:has-access="!!overview.server.has_wireguard_access"
			:can-manage-network="canManageNetwork"
			@changed="emit('changed')"
		/>

		<EditSSHKeysDialog
			v-model:open="isEditing"
			:resource-id="overview.server.resource_id"
			:keys="sshKeys"
			@saved="changed"
		/>

		<SSHKeyDialog v-model="isAdding" :save="addToServer" @saved="changed" />
	</div>
</template>
