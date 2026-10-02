<script setup lang="ts">
import { Button, Select, TextInput } from 'frappe-ui'

export interface InviteRow {
	email: string
	role: string
	/** The server's answer for this row, shown under it. */
	error: string
}

interface InviteRowsProps {
	roleOptions: { label: string; value: string }[]
	/** The role a new row starts with. */
	defaultRole: string
	disabled?: boolean
}

const props = defineProps<InviteRowsProps>()
const rows = defineModel<InviteRow[]>('rows', { required: true })

function addRow(): void {
	rows.value.push({ email: '', role: props.defaultRole, error: '' })
}

// The list always keeps one row, so removing the last one clears it instead.
function removeRow(index: number): void {
	rows.value.splice(index, 1)
	if (!rows.value.length) addRow()
}
</script>

<template>
	<div class="rounded-7 border border-outline-gray-2 p-5">
		<div
			class="mb-1.5 flex gap-2 text-sm-medium text-ink-gray-8"
			aria-hidden="true"
		>
			<span class="min-w-0 flex-1">Email address</span>
			<span class="w-36 shrink-0">Role</span>
			<span class="w-7 shrink-0" />
		</div>

		<div class="space-y-2">
			<div v-for="(row, index) in rows" :key="index">
				<div class="flex items-start gap-2">
					<TextInput
						v-model="row.email"
						class="min-w-0 flex-1"
						type="email"
						placeholder="teammate@company.com"
						:aria-label="`Email address ${index + 1}`"
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

		<Button
			class="mt-3"
			variant="subtle"
			icon-left="lucide-plus"
			label="Add another"
			:disabled="disabled"
			@click="addRow"
		/>
	</div>
</template>
