<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Dialog,
	FormControl,
	Select,
	Skeleton,
	useCall,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import EmptyState from '@/components/common/EmptyState.vue'
import { useServerMapData } from '@/composables/useServerMapData'
import { useSession } from '@/composables/useSession'
import type {
	SupportCategoryKey,
	SupportContext,
} from '@/composables/useSupport'
import {
	getSupportCategory,
	getSupportServer,
	SUPPORT_CATEGORIES,
} from '@/composables/useSupport'
import { teamParams } from '@/composables/useTeamScope'
import { timeAgo } from '@/lib/datetime'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'

interface Props {
	/** What the ticket is about, from the place the user asked for help. */
	context?: SupportContext
}

interface SupportTicket {
	name: string
	subject: string
	status: string
	creation?: string | null
	url?: string | null
}

interface CreateTicketParams {
	team: string
	category: string
	issue_type: string
	subject?: string
	description: string
	server?: string
	site?: string
}

const props = withDefaults(defineProps<Props>(), { context: () => ({}) })
const open = defineModel<boolean>('open', { required: true })
const tab = defineModel<'new' | 'open'>('tab', { required: true })

const { activeTeam } = useSession()
const { servers, sites, loaded } = useServerMapData()

const listCall = useCall<SupportTicket[], { team: string }>({
	url: method(API.listSupportTickets),
	params: teamParams,
	immediate: false,
	refetch: true,
})

const createCall = useCall<SupportTicket, CreateTicketParams>({
	url: method(API.createSupportTicket),
	method: 'POST',
	immediate: false,
})

const category = ref<SupportCategoryKey | ''>('')
const issueType = ref('')
const serverId = ref('')
const siteName = ref('')
const subject = ref('')
const description = ref('')
const formError = ref('')
const creating = ref(false)

const ticketCount = computed(() => listCall.data?.length ?? 0)
const selectedCategory = computed(() =>
	category.value ? SUPPORT_CATEGORIES[category.value] : null,
)

const contextServer = computed(() => getSupportServer(props.context))

/** The fleet, plus the server a surface named when the fleet has not loaded yet. */
const serverOptions = computed(() => {
	const options = servers.value.map((server) => ({
		value: server.resource_id,
		label: server.title
			? `${server.title} (${server.resource_id})`
			: server.resource_id,
	}))
	const named = contextServer.value
	if (named && !options.some((option) => option.value === named.resource_id))
		options.push({
			value: named.resource_id,
			label: named.title
				? `${named.title} (${named.resource_id})`
				: named.resource_id,
		})
	return options
})

/** Only the selected server's sites, so the ticket names a machine the team owns. */
const siteOptions = computed(() => {
	const serverName =
		servers.value.find((server) => server.resource_id === serverId.value)
			?.name ?? contextServer.value?.name
	return sites.value
		.filter((site) => !serverName || site.server === serverName)
		.map((site) => ({
			value: site.name,
			label: site.subdomain ? `${site.subdomain} (${site.name})` : site.name,
		}))
})

const selectedServer = computed(
	() =>
		servers.value.find((server) => server.resource_id === serverId.value) ??
		contextServer.value,
)

const serverSummary = computed(() => {
	const server = selectedServer.value
	if (!server) return ''
	return [server.region, server.plan, server.status].filter(Boolean).join(' · ')
})

const issueOptions = computed(() =>
	(selectedCategory.value?.issues ?? []).map((issue) => ({
		value: issue,
		label: issue,
	})),
)

const canSubmit = computed(
	() =>
		Boolean(category.value) &&
		Boolean(issueType.value) &&
		Boolean(description.value.trim()),
)

function resetForm(): void {
	category.value = getSupportCategory(props.context) ?? ''
	issueType.value = matchingIssue(props.context.Topic)
	serverId.value =
		contextServer.value?.resource_id ?? matchingServer(props.context.Server)
	siteName.value = matchingSite(props.context.Site)
	subject.value = ''
	description.value = ''
	formError.value = ''
}

function matchingIssue(topic: SupportContext[string]): string {
	if (typeof topic !== 'string' || !topic) return ''
	const issues = category.value ? SUPPORT_CATEGORIES[category.value].issues : []
	return issues.find((issue) => issue === topic) ?? ''
}

function matchingServer(reference: SupportContext[string]): string {
	if (typeof reference !== 'string' || !reference) return ''
	const server = servers.value.find(
		(candidate) =>
			candidate.resource_id === reference ||
			`${candidate.title} (${candidate.resource_id})` === reference,
	)
	return server?.resource_id ?? ''
}

function matchingSite(address: SupportContext[string]): string {
	if (typeof address !== 'string' || !address) return ''
	const site = sites.value.find(
		(candidate) =>
			candidate.name === address || candidate.subdomain === address,
	)
	return site?.name ?? ''
}

async function loadTickets(): Promise<void> {
	await listCall.reload()
}

async function submit(): Promise<void> {
	if (!canSubmit.value || creating.value) return

	creating.value = true
	formError.value = ''
	try {
		await submitOrThrow(createCall, {
			team: activeTeam.value!,
			category: category.value as string,
			issue_type: issueType.value,
			subject: subject.value.trim(),
			description: description.value.trim(),
			server: serverId.value || undefined,
			site: siteName.value || undefined,
		})
		successToast('Support ticket created')
		resetForm()
		// The tab watcher loads the list, so the new ticket is there when it shows.
		tab.value = 'open'
	} catch (error) {
		formError.value = getErrorMessage(error, "The ticket couldn't be created.")
	} finally {
		creating.value = false
	}
}

// A new server leaves the previously picked site out of the filtered list.
watch(serverId, () => {
	if (
		siteName.value &&
		!siteOptions.value.some((o) => o.value === siteName.value)
	)
		siteName.value = ''
})

// The issue belongs to a category, so a switch drops one that no longer fits.
watch(category, (value) => {
	if (!value) return
	if (!SUPPORT_CATEGORIES[value].issues.includes(issueType.value))
		issueType.value = ''
})

// The fleet loads after the dialog opens, so the context fills in when it lands.
watch(loaded, (isLoaded) => {
	if (!isLoaded || !open.value) return
	serverId.value ||= matchingServer(props.context.Server)
	siteName.value ||= matchingSite(props.context.Site)
})

watch(open, (isOpen) => {
	if (!isOpen) return
	resetForm()
	if (tab.value === 'open') loadTickets()
})

watch(tab, (value) => {
	if (open.value && value === 'open') loadTickets()
})

// Another surface can open the dialog while it is already open, with new context.
watch(
	() => props.context,
	() => {
		if (open.value) resetForm()
	},
)
</script>

<template>
	<Dialog
		v-model="open"
		title="Contact support"
		size="lg"
		:dismissible="!creating"
	>
		<div
			class="inline-flex gap-1 rounded-6 bg-surface-gray-2 p-1"
			role="group"
			aria-label="Support tickets"
		>
			<button
				type="button"
				class="rounded-4 px-3 py-1.5 text-p-sm"
				:class="
					tab === 'new'
						? 'bg-surface-base text-ink-gray-9 shadow-sm'
						: 'text-ink-gray-6 hover:text-ink-gray-8'
				"
				:aria-pressed="tab === 'new'"
				@click="tab = 'new'"
			>
				New ticket
			</button>
			<button
				type="button"
				class="flex items-center rounded-4 px-3 py-1.5 text-p-sm"
				:class="
					tab === 'open'
						? 'bg-surface-base text-ink-gray-9 shadow-sm'
						: 'text-ink-gray-6 hover:text-ink-gray-8'
				"
				:aria-pressed="tab === 'open'"
				@click="tab = 'open'"
			>
				Open tickets
				<Badge
					v-if="ticketCount"
					class="ml-1.5"
					theme="gray"
					size="sm"
					:label="ticketCount"
				/>
			</button>
		</div>

		<template v-if="tab === 'new'">
			<form class="mt-4 space-y-4" @submit.prevent="submit">
				<div>
					<p class="mb-2 text-p-sm text-ink-gray-7">
						What is the ticket about?
					</p>
					<div v-if="!category" class="grid grid-cols-2 gap-2">
						<button
							v-for="(option, key) in SUPPORT_CATEGORIES"
							:key="key"
							type="button"
							class="flex items-start gap-3 rounded-6 border border-outline-gray-2 bg-surface-base p-3 text-start hover:border-outline-gray-4 hover:bg-surface-gray-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							@click="category = key as SupportCategoryKey"
						>
							<span
								:class="[option.icon, 'mt-0.5 size-4 shrink-0 text-ink-gray-6']"
								aria-hidden="true"
							/>
							<span class="min-w-0">
								<span class="block text-p-sm text-ink-gray-8"
									>{{ option.label }}</span
								>
								<span class="mt-0.5 block text-p-xs text-ink-gray-5"
									>{{ option.description }}</span
								>
							</span>
						</button>
					</div>
					<div v-else class="flex items-center justify-between gap-2">
						<p class="flex items-center gap-2 text-p-sm text-ink-gray-8">
							<span
								:class="[
									selectedCategory?.icon,
									'size-4 text-ink-gray-6',
								]"
								aria-hidden="true"
							/>
							{{ selectedCategory?.label }}
						</p>
						<Button
							variant="ghost"
							size="sm"
							label="Change"
							@click="category = ''"
						/>
					</div>
				</div>

				<template v-if="category">
					<Select
						v-model="issueType"
						label="What is the issue?"
						:options="issueOptions"
						placeholder="Choose the closest match"
						required
					/>

					<div
						v-if="category === 'server' || category === 'site'"
						class="grid gap-3"
					>
						<Select
							v-if="serverOptions.length"
							v-model="serverId"
							label="Server"
							:options="serverOptions"
							placeholder="Not about one server"
							side="bottom"
						/>
						<div
							v-if="selectedServer"
							class="flex items-center gap-2 rounded-4 bg-surface-gray-2 px-2.5 py-1.5 text-p-xs text-ink-gray-6"
						>
							<span class="lucide-server size-3.5" aria-hidden="true" />
							<span class="truncate">
								{{ selectedServer.title || selectedServer.resource_id }}
								<span v-if="serverSummary"> · {{ serverSummary }}</span>
							</span>
						</div>

						<Select
							v-if="siteOptions.length"
							v-model="siteName"
							label="Site"
							:options="siteOptions"
							placeholder="Not about one site"
							side="bottom"
						/>
					</div>
				</template>

				<FormControl
					v-model="subject"
					label="Subject"
					placeholder="Brief summary"
					maxlength="140"
					description="Optional. The category and issue already start the ticket subject."
				/>
				<FormControl
					v-model="description"
					type="textarea"
					:rows="5"
					label="What happened?"
					placeholder="What were you doing, what did you expect, and what error did you see?"
					required
				/>

				<Alert v-if="formError" theme="red" :title="formError" />

				<div class="flex items-center justify-end gap-2">
					<Button label="Cancel" :disabled="creating" @click="open = false" />
					<Button
						type="submit"
						variant="solid"
						label="Create ticket"
						:loading="creating"
						:disabled="!canSubmit"
					/>
				</div>
			</form>
		</template>

		<div v-else class="mt-4">
			<div
				v-if="listCall.loading && !listCall.data"
				class="space-y-2"
				aria-busy="true"
			>
				<Skeleton v-for="index in 3" :key="index" class="h-14 rounded-6" />
			</div>

			<EmptyState
				v-else-if="listCall.error"
				icon="lucide-cloud-off"
				title="Tickets couldn't load"
				:description="
							getErrorMessage(listCall.error, 'Try again in a moment.')
						"
			>
				<template #action>
					<Button label="Retry" @click="loadTickets" />
				</template>
			</EmptyState>

			<EmptyState
				v-else-if="!ticketCount"
				icon="lucide-life-buoy"
				title="No open tickets"
				description="A ticket you create stays here until support closes it."
			>
				<template #action>
					<Button variant="solid" label="Create ticket" @click="tab = 'new'" />
				</template>
			</EmptyState>

			<ul
				v-else
				class="divide-y divide-outline-gray-1 rounded-6 border border-outline-gray-2"
			>
				<li
					v-for="ticket in listCall.data"
					:key="ticket.name"
					class="flex items-center gap-3 px-3 py-2.5"
				>
					<div class="min-w-0 flex-1">
						<p class="truncate text-p-sm text-ink-gray-8">
							{{ ticket.subject }}
						</p>
						<p class="mt-0.5 text-p-xs text-ink-gray-5">
							#{{ ticket.name }}
							<span v-if="ticket.creation">
								· {{ timeAgo(ticket.creation) }}</span
							>
						</p>
					</div>
					<Badge
						theme="blue"
						variant="subtle"
						size="sm"
						:label="ticket.status"
					/>
					<a
						v-if="ticket.url"
						:href="ticket.url"
						target="_blank"
						rel="noopener noreferrer"
						class="shrink-0 rounded-4 p-1 text-ink-gray-5 hover:bg-surface-gray-2 hover:text-ink-gray-8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
						:aria-label="`Open ticket #${ticket.name} in Helpdesk`"
					>
						<span class="lucide-external-link size-4" aria-hidden="true" />
					</a>
				</li>
			</ul>
		</div>
	</Dialog>
</template>
