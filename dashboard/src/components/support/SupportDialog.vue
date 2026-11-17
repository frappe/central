<script setup lang="ts">
import { Badge, Button, Dialog, useCall } from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import SupportAsk from '@/components/support/SupportAsk.vue'
import SupportContactForm from '@/components/support/SupportContactForm.vue'
import SupportTicketList from '@/components/support/SupportTicketList.vue'
import { useSession } from '@/composables/useSession'
import {
	type SupportCategoryOption,
	type SupportContext,
	type SupportTicket,
	useSupport,
} from '@/composables/useSupport'
import {
	contactAction,
	getOutageIssue,
	type OutageIssue,
	useSupportAnswers,
} from '@/composables/useSupportAnswers'
import { teamParams } from '@/composables/useTeamScope'

interface Props {
	/** What the ticket is about, from the place the user asked for help. */
	context?: SupportContext
}

const props = withDefaults(defineProps<Props>(), { context: () => ({}) })
const open = defineModel<boolean>('open', { required: true })
const tab = defineModel<'new' | 'open'>('tab', { required: true })

const { activeTeam } = useSession()
// Without help articles there is nothing to search first, so the dialog starts on the form.
const startStage = useSupport().isAnswersFirst ? 'ask' : 'contact'
const creating = ref(false)
const openCount = ref(0)
const stage = ref<'ask' | 'contact' | 'tickets'>(startStage)
const askQuery = ref('')
const presetIssue = ref<OutageIssue | null>(null)
const ask = ref<InstanceType<typeof SupportAsk> | null>(null)

const related = useSupportAnswers(activeTeam)

const optionsCall = useCall<SupportCategoryOption[], { team: string }>({
	url: method(API.getTicketOptions),
	params: teamParams,
	immediate: false,
})

const listCall = useCall<SupportTicket[], { team: string }>({
	url: method(API.listSupportTickets),
	params: teamParams,
	immediate: false,
	refetch: true,
})

const ticketCount = computed(() => listCall.data?.length ?? 0)
const openTickets = computed(() => listCall.data ?? [])
const action = computed(() =>
	contactAction({
		query: askQuery.value,
		isLoading: related.loading.value,
		hasResults: !related.error.value && related.resultCount.value > 0,
	}),
)

async function loadOptions(): Promise<void> {
	if (optionsCall.data || optionsCall.loading) return
	await optionsCall.reload()
}

async function loadTickets(): Promise<void> {
	await listCall.reload()
}

function showTickets(): void {
	tab.value = 'open'
	loadTickets()
}

function goToContact(): void {
	presetIssue.value = null
	stage.value = 'contact'
	related.stop()
}

function reportOutage(): void {
	presetIssue.value = getOutageIssue(props.context)
	stage.value = 'contact'
	related.stop()
}

const title = computed(
	() =>
		({ ask: 'Get help', contact: 'Contact support', tickets: 'Your tickets' })[
			stage.value
		],
)

function goBack(): void {
	if (stage.value === 'tickets') tab.value = 'new'
	else stage.value = startStage
	nextTick(() => ask.value?.focus())
}

function onCreated(): void {
	tab.value = 'open'
	loadTickets()
}

watch(askQuery, () => related.refresh(askQuery.value))

watch(
	tab,
	(value) => {
		stage.value = value === 'open' ? 'tickets' : startStage
	},
	{ immediate: true },
)

watch(
	open,
	(isOpen) => {
		if (!isOpen) return
		openCount.value += 1
		askQuery.value = ''
		presetIssue.value = null
		stage.value = tab.value === 'open' ? 'tickets' : startStage
		related.stop()
		loadOptions()
		loadTickets()
	},
	{ immediate: true },
)
</script>

<template>
	<Dialog v-model="open" size="xl" :dismissible="!creating">
		<template #title>
			<div class="flex items-center justify-between gap-2 pr-2">
				<div class="flex items-center gap-1.5">
					<Button
						v-if="stage !== startStage"
						variant="ghost"
						icon="lucide-arrow-left"
						:aria-label="__('Back')"
						:disabled="creating"
						@click="goBack"
					/>
					<h3 class="text-2xl-semibold leading-6 text-ink-gray-8">
						{{ title }}
					</h3>
				</div>
				<Button
					v-if="stage === startStage"
					variant="subtle"
					icon-left="lucide-ticket"
					:label="__('Your tickets')"
					@click="showTickets"
				>
					<template v-if="ticketCount" #suffix>
						<Badge theme="gray" size="sm" :label="ticketCount" />
					</template>
				</Button>
			</div>
		</template>

		<div class="flex h-[28rem] max-h-[calc(100vh-12rem)] flex-col">
			<SupportAsk
				ref="ask"
				v-if="stage === 'ask'"
				:key="`ask-${openCount}`"
				v-model:query="askQuery"
				:context="props.context"
				:action="action"
				:loading="related.loading.value"
				:error="related.error.value"
				:articles="related.articles.value"
				:tickets="related.tickets.value"
				:open-tickets="openTickets"
				@contact="goToContact"
				@outage="reportOutage"
			/>

			<SupportContactForm
				v-else-if="stage === 'contact'"
				:key="`contact-${openCount}`"
				:context="props.context"
				:options="optionsCall.data ?? []"
				:options-loading="optionsCall.loading"
				:options-finished="optionsCall.isFinished"
				:options-error="optionsCall.error"
				:ask-text="askQuery"
				:preset="presetIssue"
				@created="onCreated"
				@creating="creating = $event"
				@cancel="open = false"
				@retry-options="loadOptions"
			/>

			<SupportTicketList
				v-else
				:tickets="listCall.data"
				:loading="listCall.loading"
				:error="listCall.error"
				@retry="loadTickets"
				@create="tab = 'new'"
			/>
		</div>
	</Dialog>
</template>
