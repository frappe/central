<script setup lang="ts">
import { Badge, Button, LoadingText } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AssignProjectDialog from '@/components/billing/AssignProjectDialog.vue'
import CreateProjectDialog from '@/components/billing/CreateProjectDialog.vue'
import PayingForTable from '@/components/billing/PayingForTable.vue'
import ProjectMembersDialog from '@/components/billing/ProjectMembersDialog.vue'
import RenameProjectDialog from '@/components/billing/RenameProjectDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayingFor } from '@/composables/usePayingFor'
import { useProjects } from '@/composables/useProjects'
import { money } from '@/lib/format'
import { subscriptionTitle } from '@/lib/subscriptions'

const VISIBLE = 5

defineEmits<{ open: []; openProjects: [] }>()

const router = useRouter()
const { canManageBilling } = useCapabilities()

const {
	rows,
	loading,
	currency,
	total,
	busy,
	pendingPause,
	pendingAssignProject,
	openServer,
	askPause,
	confirmPause,
	onResume,
	askAssignProject,
	onAssignedProject,
} = usePayingFor()

const {
	projects,
	pendingRename,
	pendingManageMembers,
	manageMembersOpen,
	reloadProjects,
} = useProjects()

const showCreate = ref(false)
const projectCount = computed(() => projects.data?.length ?? 0)

const visible = computed(() => rows.value.slice(0, VISIBLE))
const hidden = computed(() => Math.max(0, rows.value.length - VISIBLE))
const goToObjectStorage = () => router.push({ name: 'ObjectStorage' })
</script>

<template>
	<section
		aria-labelledby="subscriptions-heading"
		class="overflow-hidden rounded-6 border border-outline-gray-1 bg-surface-base"
	>
		<header class="flex items-center justify-between gap-3 px-4 py-3">
			<h2 id="subscriptions-heading" class="text-base-semibold text-ink-gray-8">
				Subscriptions
				<Badge v-if="rows.length" class="ml-1" :label="String(rows.length)" />
			</h2>
			<span class="text-sm tabular-nums text-ink-gray-5">
				{{ money(total, currency) }}
				this cycle
			</span>
		</header>

		<LoadingText v-if="loading" :lines="3" class="px-4 pb-5" />

		<div v-else>
			<div
				v-if="!rows.length"
				class="flex flex-wrap items-center justify-between gap-3 border-t border-outline-gray-1 px-4 py-4"
			>
				<p class="text-p-sm text-ink-gray-5">
					Servers and metered services you subscribe to show here with what they
					cost.
				</p>
				<Button
					v-if="canManageBilling"
					label="Open Object Storage"
					@click="goToObjectStorage"
				/>
			</div>

			<PayingForTable
				show-projects
				:hide-header="!rows.length"
				:rows="visible"
				:project-count="projectCount"
				:currency="currency"
				:can-manage="canManageBilling"
				:busy="busy"
				@open="openServer"
				@pause="askPause"
				@resume="onResume"
				@assign-project="askAssignProject"
				@open-projects="$emit('openProjects')"
				@new-project="showCreate = true"
			/>
			<button
				v-if="hidden"
				type="button"
				class="flex w-full items-center gap-1 border-t border-outline-gray-1 px-4 py-2.5 text-sm text-ink-gray-5 transition-colors hover:bg-surface-gray-1 hover:text-ink-gray-8"
				@click="$emit('open')"
			>
				View all {{ rows.length }}
				<span class="lucide-arrow-right size-3.5" aria-hidden="true" />
			</button>
		</div>

		<CreateProjectDialog v-model="showCreate" @created="reloadProjects" />
		<RenameProjectDialog
			v-model:project="pendingRename"
			@saved="reloadProjects"
		/>
		<ProjectMembersDialog
			v-model:open="manageMembersOpen"
			:project="pendingManageMembers"
			@changed="reloadProjects"
		/>

		<ConfirmDialog
			v-model:target="pendingPause"
			title="Pause billing"
			:message="`Pause billing for ${pendingPause ? subscriptionTitle(pendingPause) : ''}? This stops the server/VM and the site(s)/services running on it, and stops charges until you resume.`"
			confirm-label="Pause billing"
			:loading="busy === pendingPause?.name"
			@confirm="confirmPause"
		/>
		<AssignProjectDialog
			v-model:subscription="pendingAssignProject"
			@assigned="onAssignedProject"
		/>
	</section>
</template>
