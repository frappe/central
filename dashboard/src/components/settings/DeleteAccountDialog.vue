<script setup lang="ts">
import { Alert, Button, LoadingIndicator } from 'frappe-ui'
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import {
	type OwnedTeam,
	useAccountDeletion,
} from '@/composables/useAccountDeletion'
import { useSession } from '@/composables/useSession'
import { settingsOpen } from '@/composables/useSettings'
import { useSupport } from '@/composables/useSupport'
import type { ArchiveCheck } from '@/composables/useTeamArchiveChecks'
import { CHECK_COPY, describeCheck } from '@/lib/archiveChecks'
import { money } from '@/lib/format'

interface DeleteAccountDialogProps {
	/** The signed-in user's email; null closes the dialog. */
	target: string | null
	deleting: boolean
	error: string
}

const props = defineProps<DeleteAccountDialogProps>()
const emit = defineEmits<{
	'update:target': [value: string | null]
	delete: []
}>()

const router = useRouter()
const { setActiveTeam } = useSession()
const { getTicketUrl } = useSupport()

const supportUrls = computed<Record<string, string | undefined>>(() =>
	Object.fromEntries(
		teams.value.map((team) => [
			team.team,
			getTicketUrl({ Team: team.team_name }) ?? undefined,
		]),
	),
)
const {
	teams,
	loading,
	error: checksError,
	isClear,
	reload,
} = useAccountDeletion()

const target = computed({
	get: () => props.target,
	set: (value: string | null) => emit('update:target', value),
})

const creditText = computed(() =>
	teams.value
		.flatMap((team) => team.credit_balances)
		.map((credit) => money(credit.balance, credit.currency))
		.join(' and '),
)

const teamNames = computed(() =>
	teams.value.map((team) => team.team_name).join(', '),
)

const todos = computed(() =>
	teams.value.flatMap((team) =>
		team.checks
			.filter((check) => !check.passed)
			.map((check) => ({ team, check })),
	),
)

let pendingFix: { team: string; route?: string } | null = null

function openFix(team: OwnedTeam, check: ArchiveCheck): void {
	pendingFix = { team: team.team, route: CHECK_COPY[check.key].route }
	target.value = null
}

/** Close settings only after this dialog has left, or its overlay stays behind. */
function onAfterLeave(): void {
	if (!pendingFix) return
	const { team, route } = pendingFix
	pendingFix = null
	settingsOpen.value = false
	setActiveTeam(team)
	if (route) router.push(route)
}

/** The user may clear an item in another tab, so check again when they come back. */
function onFocus(): void {
	if (props.target) reload()
}

watch(
	() => props.target,
	(email) => {
		if (email) reload()
	},
)
window.addEventListener('focus', onFocus)
onBeforeUnmount(() => window.removeEventListener('focus', onFocus))
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		title="Delete account"
		confirm-label="Delete account"
		theme="red"
		size="md"
		:loading="deleting"
		:error="error"
		:disabled="!isClear"
		:confirm-text="isClear ? (target ?? undefined) : undefined"
		@confirm="emit('delete')"
		@after-leave="onAfterLeave"
	>
		<div class="space-y-6">
			<p class="text-p-base text-ink-gray-8">
				We remove your profile and your access to every team<template
					v-if="teams.length"
					>, and archive
					<span class="text-p-base-semibold text-ink-gray-9"
						>{{ teamNames }}</span
					></template
				>. Invoices are kept, as the law requires.
			</p>

			<Alert
				v-if="creditText"
				theme="amber"
				:title="`You lose ${creditText} of team credit`"
			/>

			<div
				v-if="loading && !teams.length"
				class="flex items-center gap-2 text-p-sm text-ink-gray-5"
			>
				<LoadingIndicator class="size-4" />
				Checking your teams…
			</div>
			<Alert v-else-if="checksError" theme="red" :title="checksError">
				<Button label="Try again" @click="reload" />
			</Alert>
			<section v-else-if="todos.length" class="space-y-3">
				<div>
					<h3 class="text-base-semibold text-ink-gray-9">
						You can't delete your account yet
					</h3>
					<p class="mt-1 text-p-sm text-ink-gray-5">
						Finish these first. Delete turns on when the list is clear.
					</p>
				</div>
				<ul
					class="divide-y divide-outline-gray-1 rounded-6 border border-outline-gray-2"
					aria-label="Finish these first"
				>
					<li
						v-for="{ team, check } in todos"
						:key="`${team.team}-${check.key}`"
						class="flex items-center gap-3 px-3 py-2.5"
					>
						<span
							aria-hidden="true"
							class="lucide-circle-alert size-4 shrink-0 text-ink-red-6"
						/>
						<div class="min-w-0 flex-1">
							<p class="text-base text-ink-gray-8">
								<span class="sr-only">To do:</span>
								{{ describeCheck(check) }}
							</p>
							<p class="mt-1 truncate text-sm text-ink-gray-5">
								{{ team.team_name }}
							</p>
						</div>
						<template v-if="check.key === 'suspended'">
							<Button
								v-if="supportUrls[team.team]"
								variant="ghost"
								icon-right="lucide-external-link"
								:label="CHECK_COPY[check.key].action"
								:href="supportUrls[team.team]"
							/>
						</template>
						<Button
							v-else
							variant="ghost"
							icon-right="lucide-arrow-right"
							:label="CHECK_COPY[check.key].action"
							@click="openFix(team, check)"
						/>
					</li>
				</ul>
			</section>

			<p v-if="isClear" class="text-p-sm text-ink-gray-5">
				We email you a link to confirm. You can cancel for 3 days.
			</p>
		</div>
	</ConfirmDialog>
</template>
