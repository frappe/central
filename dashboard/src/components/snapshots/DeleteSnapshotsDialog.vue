<script setup lang="ts">
import { computed } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import type { VMSnapshotRow } from '@/types/snapshots'

interface DeleteSnapshotsDialogProps {
	target: VMSnapshotRow[] | null
	loading?: boolean
	error?: string
}

const props = defineProps<DeleteSnapshotsDialogProps>()
const emit = defineEmits<{
	'update:target': [value: VMSnapshotRow[] | null]
	confirm: [value: VMSnapshotRow[]]
}>()

const target = computed({
	get: () => props.target,
	set: (value: VMSnapshotRow[] | null) => emit('update:target', value),
})
const title = computed(() =>
	(props.target?.length ?? 0) > 1
		? `Delete ${props.target?.length} snapshots`
		: 'Delete snapshot',
)
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		:title="title"
		confirm-label="Yes, delete"
		theme="red"
		size="md"
		:loading="loading"
		:error="error"
		@confirm="emit('confirm', $event)"
	>
		<div v-if="target" class="space-y-2">
			<p class="text-p-base text-ink-gray-7">
				A deleted snapshot cannot be restored, and its storage stops costing
				money.
			</p>
			<ul
				class="max-h-40 space-y-1 overflow-y-auto rounded-6 border border-outline-gray-2 px-3 py-2"
			>
				<li
					v-for="snapshot in target"
					:key="snapshot.name"
					class="truncate text-p-sm text-ink-gray-9"
				>
					{{ snapshot.title }}
					<span class="text-ink-gray-5">· {{ snapshot.server_title }}</span>
				</li>
			</ul>
		</div>
	</ConfirmDialog>
</template>
