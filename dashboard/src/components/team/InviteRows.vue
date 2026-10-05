<script setup lang="ts">
import { Button, Select, TextInput } from 'frappe-ui'
import {
	ALL_RESOURCES,
	type InviteRow,
	MAX_INVITATIONS,
} from '@/composables/useBulkInvite'

type Option = { label: string; value: string; description?: string }

interface InviteRowsProps {
	roleOptions: Option[]
	/** Shows a Resource column when given. Without it, every row covers the whole team. */
	resourceOptions?: Option[]
	/** The role a new row starts with. */
	defaultRole: string
	disabled?: boolean
}

const props = defineProps<InviteRowsProps>()
const rows = defineModel<InviteRow[]>('rows', { required: true })

function addRow(): void {
	rows.value.push({
		email: '',
		role: props.defaultRole,
		resource: ALL_RESOURCES,
		error: '',
	})
}

// The list always keeps one row, so removing the last one clears it instead.
function removeRow(index: number): void {
	rows.value.splice(index, 1)
	if (!rows.value.length) addRow()
}
</script>

<template>
	<div>
		<div
			class="mb-2 flex gap-3 text-sm-medium text-ink-gray-6"
			aria-hidden="true"
		>
			<span class="min-w-0 flex-1">Email</span>
			<span class="w-36 shrink-0">Role</span>
			<span v-if="resourceOptions" class="w-44 shrink-0">Resource</span>
			<span class="w-7 shrink-0" />
		</div>

		<div class="space-y-3">
			<div v-for="(row, index) in rows" :key="index">
				<div class="flex items-start gap-3">
					<TextInput
						v-model="row.email"
						class="min-w-0 flex-1"
						type="email"
						v-focus="index === 0"
						placeholder="teammate@company.com"
						:aria-label="`Email ${index + 1}`"
						:disabled="disabled"
						@update:model-value="row.error = ''"
					/>
					<Select
						v-model="row.role"
						class="w-36 shrink-0"
						:options="roleOptions"
						placeholder="Role"
						:aria-label="`Role ${index + 1}`"
						:disabled="disabled"
					/>
					<Select
						v-if="resourceOptions"
						v-model="row.resource"
						class="w-44 shrink-0"
						:options="resourceOptions"
						:aria-label="`Resource ${index + 1}`"
						:disabled="disabled"
					/>
					<Button
						variant="ghost"
						icon="lucide-x"
						:aria-label="`Remove ${row.email || `row ${index + 1}`}`"
						:disabled="disabled"
						@click="removeRow(index)"
					/>
				</div>
				<p v-if="row.error" class="mt-1 text-p-xs text-ink-red-7">
					{{ row.error }}
				</p>
			</div>
		</div>

		<div class="mt-4 flex items-center gap-3">
			<Button
				variant="subtle"
				icon-left="lucide-plus"
				label="Add another"
				:disabled="disabled || rows.length >= MAX_INVITATIONS"
				@click="addRow"
			/>
			<p
				v-if="rows.length >= MAX_INVITATIONS"
				class="text-p-sm text-ink-gray-5"
			>
				You can invite up to {{ MAX_INVITATIONS }} people at a time.
			</p>
		</div>
	</div>
</template>
