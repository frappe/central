<script setup lang="ts">
import { Alert, Button, LoadingIndicator } from 'frappe-ui'
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
import { useSession } from '@/composables/useSession'
import { settingsOpen } from '@/composables/useSettings'
import {
	type ArchiveCheck,
	type ArchiveCheckKey,
	useTeamArchiveChecks,
} from '@/composables/useTeamArchiveChecks'
import { money, plural } from '@/lib/format'

interface ArchiveTeamDialogProps {
	/** The team to archive; null closes the dialog. */
	target: string | null
	archiving: boolean
	error: string
}

interface CheckCopy {
	passed: string
	failed: (count: number) => string
	action: string
	route: string
}

const props = defineProps<ArchiveTeamDialogProps>()
const emit = defineEmits<{
	'update:target': [value: string | null]
	archive: []
}>()

const router = useRouter()
const { activeTeamLabel } = useSession()
const {
	checks,
	creditBalances,
	loading,
	error: checksError,
	isClear,
	reload,
} = useTeamArchiveChecks()

const CHECK_COPY: Record<ArchiveCheckKey, CheckCopy> = {
	servers: {
		passed: 'All servers are terminated',
		failed: (count) => `${plural(count, 'server')} not terminated`,
		action: 'Open servers',
		route: '/servers',
	},
	snapshots: {
		passed: 'No paid snapshots',
		failed: (count) => `${plural(count, 'paid snapshot')} to delete`,
		action: 'Open snapshots',
		route: '/servers/snapshots',
	},
	buckets: {
		passed: 'No buckets',
		failed: (count) => `${plural(count, 'bucket subscription')} still billing`,
		action: 'Open storage',
		route: '/object-storage',
	},
	add_ons: {
		passed: 'No other paid add-ons',
		failed: (count) => `${plural(count, 'other paid add-on')} still billing`,
		action: 'Open billing',
		route: '/billing',
	},
	invoices: {
		passed: 'No unpaid invoices',
		failed: (count) => plural(count, 'unpaid invoice'),
		action: 'Pay invoices',
		route: '/billing/invoices',
	},
	final_bill: {
		passed: "This month's charges can be collected",
		failed: () => "This month's charges need a payment method",
		action: 'Add a card',
		route: '/billing',
	},
}

const creditText = computed(() =>
	creditBalances.value
		.map((credit) => money(credit.balance, credit.currency))
		.join(' and '),
)

const target = computed({
	get: () => props.target,
	set: (value: string | null) => emit('update:target', value),
})

function describe(check: ArchiveCheck): string {
	const copy = CHECK_COPY[check.key]
	return check.passed ? copy.passed : copy.failed(check.count)
}

function openFix(check: ArchiveCheck): void {
	target.value = null
	settingsOpen.value = false
	router.push(CHECK_COPY[check.key].route)
}

// An owner may settle an invoice in another tab; check again when they come back.
function onFocus(): void {
	if (props.target) reload()
}

watch(
	() => props.target,
	(team) => {
		if (team) reload()
	},
)
window.addEventListener('focus', onFocus)
onBeforeUnmount(() => window.removeEventListener('focus', onFocus))
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		title="Archive team"
		confirm-label="Archive team"
		theme="red"
		size="md"
		:loading="archiving"
		:error="error"
		:disabled="!isClear"
		:confirm-text="isClear ? activeTeamLabel : undefined"
		@confirm="emit('archive')"
	>
		<div class="space-y-4">
			<p class="text-p-base text-ink-gray-7">
				Every member of
				<span class="text-p-base-semibold text-ink-gray-9"
					>{{ activeTeamLabel }}</span
				>
				loses access. Invoices and records are kept. To use the team again,
				<ContactSupportLink :context="{ Team: activeTeamLabel }" />.
			</p>

			<div
				v-if="loading && !checks.length"
				class="flex items-center gap-2 text-p-sm text-ink-gray-5"
			>
				<LoadingIndicator class="size-4" />
				Checking the team…
			</div>
			<Alert v-else-if="checksError" theme="red" :title="checksError">
				<Button label="Try again" @click="reload" />
			</Alert>
			<ul
				v-else
				class="divide-y divide-outline-gray-1 rounded-6 border border-outline-gray-2"
				aria-label="Before you archive"
			>
				<li
					v-for="check in checks"
					:key="check.key"
					class="flex items-center gap-3 px-3 py-2.5"
				>
					<span
						aria-hidden="true"
						class="size-4 shrink-0"
						:class="
							check.passed
								? 'lucide-circle-check text-ink-green-6'
								: 'lucide-circle-alert text-ink-red-6'
						"
					/>
					<span class="min-w-0 flex-1 text-p-sm text-ink-gray-8">
						<span class="sr-only">{{ check.passed ? 'Done:' : 'To do:' }}</span>
						{{ describe(check) }}
					</span>
					<Button
						v-if="!check.passed"
						size="sm"
						:label="CHECK_COPY[check.key].action"
						@click="openFix(check)"
					/>
				</li>
			</ul>

			<Alert
				v-if="creditText"
				theme="amber"
				:title="`The team has ${creditText} of credit. Archiving forfeits it.`"
			/>
		</div>
	</ConfirmDialog>
</template>
