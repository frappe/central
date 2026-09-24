<script setup lang="ts">
import { Alert, Button, MultiSelect } from 'frappe-ui'
import { computed, ref } from 'vue'
import SSHKeyDialog from '@/components/servers/SSHKeyDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamSSHKeys } from '@/composables/useTeamSSHKeys'
import type { TeamSSHKey } from '@/types/sshKeys'

interface Props {
	modelValue: string[]
	required: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const { keys, loading, error, reload, create } = useTeamSSHKeys()
const { canManageSSHKeys } = useCapabilities()
const adding = ref(false)
const options = computed(() =>
	keys.value.map((key) => ({
		label: key.title,
		value: key.name,
		description: key.fingerprint,
	})),
)

function updateSelection(values: Array<string | number>) {
	emit('update:modelValue', values.map(String))
}

function addKey(setOpen: (value: boolean) => void) {
	setOpen(false)
	adding.value = true
}

function saved(key: TeamSSHKey | null) {
	if (key && !props.modelValue.includes(key.name)) {
		emit('update:modelValue', [...props.modelValue, key.name])
	}
}
</script>

<template>
	<div class="space-y-3">
		<MultiSelect
			:model-value="modelValue"
			:options="options"
			:loading="loading"
			:disabled="!!error"
			:required="required"
			:description="
				required
					? 'Select at least one team key to sign in to Ubuntu.'
					: 'Add a team key if you want SSH access to this server.'
			"
			:empty-text="keys.length ? 'No matching keys' : 'No team SSH keys yet'"
			label="SSH keys"
			placeholder="Select team SSH keys"
			variant="outline"
			class="w-full max-w-xs"
			@update:model-value="updateSelection"
		>
			<template #item-label="{ item }">
				<div class="min-w-0">
					<div class="truncate">{{ item.label }}</div>
					<div class="truncate font-mono text-p-sm text-ink-gray-5">
						{{ item.description }}
					</div>
				</div>
			</template>
			<template #footer="{ clear, selectedOptions, setOpen }">
				<div
					v-if="keys.length || canManageSSHKeys"
					class="flex items-center justify-between gap-2 border-t border-outline-gray-1 px-2 py-1.5"
				>
					<Button
						v-if="selectedOptions.length"
						variant="ghost"
						size="sm"
						label="Clear all"
						@click="clear"
					/>
					<Button
						v-if="canManageSSHKeys"
						variant="ghost"
						size="sm"
						icon-left="lucide-plus"
						label="Add SSH key"
						@click="addKey(setOpen)"
					/>
				</div>
			</template>
		</MultiSelect>
		<Alert
			v-if="error"
			theme="red"
			title="Couldn't load SSH keys"
			:description="error"
			:primary-action="{ label: 'Retry', onClick: reload }"
		/>
		<SSHKeyDialog v-model="adding" :save="create" @saved="saved" />
	</div>
</template>
