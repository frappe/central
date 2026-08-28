<script setup lang="ts">
import { Button, Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { errorToast, successToast } from '@/lib/toast'
import type { Project, SubscriptionRow } from '@/types/billing'

// Which servers show under a Project's heading in the cost breakdown — the other
// direction of AssignProjectDialog (there you pick a project for one server;
// here you pick servers for one project). Reuses the same tag/untag endpoint
// and the team's already-loaded subscriptions — no new reads. Controlled by the
// card/panel via v-model:project, like RenameProjectDialog.
const props = defineProps<{ project: Project | null }>()
const emit = defineEmits<{
	'update:project': [project: Project | null]
	changed: []
}>()

const { subscriptions, reloadSubscriptionGrouping } = useBillingOverview()

const open = computed({
	get: () => !!props.project,
	set: (v: boolean) => {
		if (!v) emit('update:project', null)
	},
})

// Servers only — the same set PayingForCard's row action can tag (a team-level
// metered service has no "Move to project" entry point yet either).
const members = computed<SubscriptionRow[]>(() =>
	(subscriptions.data ?? []).filter(
		(s) => s.has_server && s.project === props.project?.name,
	),
)
const candidates = computed(() =>
	(subscriptions.data ?? [])
		.filter((s) => s.has_server && s.project !== props.project?.name)
		.map((s) => ({ label: s.server || s.name, value: s.name })),
)

const NONE = ''
const toAdd = ref(NONE)
watch(open, (isOpen) => {
	if (isOpen) toAdd.value = NONE
})

function serverTitle(sub: SubscriptionRow): string {
	return sub.server || sub.plan_title || sub.name
}

const assign = useCall<unknown, { subscription: string; project: string | null }>({
	url: method(API.setSubscriptionProject),
	method: 'POST',
	immediate: false,
})

// One row mutates at a time; `busy` holds its name so the row can show a spinner.
const busy = ref('')

async function addMember(): Promise<void> {
	if (!toAdd.value || !props.project) return
	busy.value = toAdd.value
	try {
		await assign.submit({ subscription: toAdd.value, project: props.project.name })
		if (assign.error) throw assign.error
		toAdd.value = NONE
		reloadSubscriptionGrouping()
		emit('changed')
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}

async function removeMember(sub: SubscriptionRow): Promise<void> {
	busy.value = sub.name
	try {
		await assign.submit({ subscription: sub.name, project: null })
		if (assign.error) throw assign.error
		successToast(`${serverTitle(sub)} removed from this project.`)
		reloadSubscriptionGrouping()
		emit('changed')
	} catch (e) {
		errorToast(e)
	} finally {
		busy.value = ''
	}
}
</script>

<template>
	<Dialog v-model="open" :title="project ? `${project.title} — servers` : ''" size="lg">
		<template #default>
			<div class="space-y-4">
				<div v-if="members.length" class="divide-y divide-outline-gray-1">
					<div
						v-for="sub in members"
						:key="sub.name"
						class="flex items-center justify-between gap-3 py-2.5"
					>
						<span class="truncate text-sm text-ink-gray-8">
							{{ serverTitle(sub) }}
						</span>
						<RowActionsMenu
							:options="[
								{
									label: 'Remove from project',
									icon: 'lucide-x',
									onClick: () => removeMember(sub),
								},
							]"
							label="Remove from project"
							icon="lucide-ellipsis"
							:busy="busy === sub.name"
						/>
					</div>
				</div>
				<p v-else class="text-p-sm text-ink-gray-5">
					No servers in this project yet — add one below.
				</p>

				<div class="flex items-end gap-2 border-t border-outline-gray-2 pt-4">
					<FormControl
						v-if="candidates.length"
						type="select"
						v-model="toAdd"
						:options="[{ label: 'Choose a server…', value: NONE }, ...candidates]"
						label="Add a server"
						class="flex-1"
					/>
					<p v-else class="text-p-sm text-ink-gray-5">
						Every server is already in this project.
					</p>
					<Button
						v-if="candidates.length"
						variant="subtle"
						label="Add"
						:disabled="!toAdd"
						@click="addMember"
					/>
				</div>
			</div>
		</template>
	</Dialog>
</template>
