<script setup lang="ts">
import { Avatar, Badge, Button, Dialog, Dialogs, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Table from '@/components/common/Table.vue'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'
import { shortDate } from '@/lib/date'
import CreateTeamDialog from './CreateTeamDialog.vue'

const open = defineModel<boolean>('open')

const { teams, activeTeam } = useSession()
const { teamColumns, teamRowActions } = useTeamSettings()

const query = ref('')
watch(open, () => {
	query.value = ''
})

watch(activeTeam, () => {
	open.value = false
})

const searchable = computed(() => teams.value.length > 6)
const visible = computed(() => {
	const q = query.value.trim().toLowerCase()
	if (!q) return teams.value
	return teams.value.filter((team) => team.label.toLowerCase().includes(q))
})

const createTeamOpen = ref(false)
const createTeam = () => {
	open.value = false
	createTeamOpen.value = true
}
</script>

<template>
	<Dialog v-model="open" size="2xl" :show-close-button="false">
		<template #title>
			<div class="flex items-start justify-between gap-3">
				<div>
					<h3 class="text-2xl-semibold leading-6 text-ink-gray-8">
						Switch team
					</h3>
					<p class="mt-1 text-p-base text-ink-gray-6">
						Each team keeps its own servers, members and billing.
					</p>
				</div>
				<Button
					variant="solid"
					icon-left="lucide-plus"
					label="Create"
					@click="createTeam"
				/>
			</div>
		</template>

		<TextInput
			v-if="searchable"
			v-model="query"
			class="mb-4"
			size="md"
			placeholder="Search teams"
			autofocus
		>
			<template #prefix>
				<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
			</template>
		</TextInput>

		<Table :columns="teamColumns" :rows="visible" height="max-h-80">
			<template #label="{ row }">
				<span class="flex items-center gap-2.5">
					<Avatar
						:image="row.logo ?? undefined"
						:label="row.label"
						shape="square"
					/>
					<span class="truncate text-base text-ink-gray-8"
						>{{ row.label }}</span
					>
					<Badge
						v-if="row.name === activeTeam"
						label="Current"
						theme="green"
					/>
				</span>
			</template>

			<template #role="{ row }">
				<Badge :label="row.role ?? 'Member'" />
			</template>

			<template #members="{ row }">
				<span class="text-p-sm text-ink-gray-6">{{ row.members }}</span>
			</template>

			<template #created="{ row }">
				<span class="text-p-sm text-ink-gray-5"
					>{{ shortDate(row.created) }}</span
				>
			</template>

			<template #actions="{ row }">
				<RowActionsMenu :options="teamRowActions(row)" label="Team actions" />
			</template>
		</Table>

		<p
			v-if="!visible.length"
			class="px-2 py-8 text-center text-p-sm text-ink-gray-5"
		>
			No team matches “{{ query.trim() }}”
		</p>
	</Dialog>

	<CreateTeamDialog v-model:open="createTeamOpen" />
	<Dialogs />
</template>
