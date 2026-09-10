<script setup lang="ts">
import { Badge, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { features } from '@/lib/features'
import { money } from '@/lib/format'

interface ServiceRow {
	resource_type: string | null
	unit: string | null
	period_usage: number
	locked_rate: number
	currency: string
}
interface ServicePlan {
	resource_type: string | null
	rate: number
}
interface MeteredServices {
	currency: string
	services: ServiceRow[]
	available_plans: ServicePlan[]
}

const { activeTeam } = useSession()

const metered = useCall<MeteredServices, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => metered.reload())

const currency = computed(() => metered.data?.currency ?? 'USD')

const CATALOG = [
	{
		resourceType: 'Tokens',
		icon: 'lucide-sparkles',
		title: 'AI inference',
		description:
			'Open models on Frappe hardware, through an OpenAI-compatible API.',
		noun: 'tokens',
		to: '/addons/ai',
		flag: 'llm' as const,
	},
	{
		resourceType: null,
		icon: 'lucide-archive',
		title: 'Object storage',
		description:
			'S3-compatible buckets for file uploads, backups and static assets.',
		noun: 'GB',
		to: '/addons/object-storage',
		flag: 'storage' as const,
	},
	{
		resourceType: 'PDF',
		icon: 'lucide-file-text',
		title: 'PDF rendering',
		description: 'PDFs from your print formats, rendered off your server.',
		noun: 'documents',
		to: null,
		flag: 'pdf' as const,
	},
	{
		resourceType: 'Emails',
		icon: 'lucide-mail',
		title: 'Email sending',
		description:
			'Send mail from your own domain. DKIM and SPF handled for you.',
		noun: 'emails',
		to: null,
		flag: 'email' as const,
	},
]

const number = new Intl.NumberFormat(undefined, {
	notation: 'compact',
	maximumFractionDigits: 1,
})

const rateOf = (resourceType: string | null): number | undefined =>
	metered.data?.services.find((s) => s.resource_type === resourceType)
		?.locked_rate ??
	metered.data?.available_plans.find((p) => p.resource_type === resourceType)
		?.rate

const rateLabel = (rate: number | undefined, noun: string): string =>
	rate == null
		? 'Pricing to be announced'
		: `${money(rate * 1000, currency.value)} per 1,000 ${noun}`

const cards = computed(() =>
	CATALOG.map((entry) => {
		const live = features[entry.flag] && !!entry.to
		const subscribed = live
			? metered.data?.services.find(
					(s) => s.resource_type === entry.resourceType,
				)
			: undefined
		const usage = subscribed?.period_usage
		return {
			...entry,
			to: live ? entry.to : '',
			live,
			on: !!subscribed,
			meta: subscribed
				? usage
					? `${number.format(usage)} ${entry.noun} this cycle`
					: 'No usage this cycle'
				: rateLabel(rateOf(entry.resourceType), entry.noun),
		}
	}),
)
</script>

<template>
	<section
		class="mx-auto lg:mt-10 grid max-w-3xl gap-3 md:gap-4 p-3 md:p-4 md:grid-cols-2"
	>
		<router-link
			v-for="service in cards"
			:key="service.title"
			:to="service.to"
			class="flex flex-col rounded-6 border p-4"
			:class="
				service.live
					? 'border-outline-gray-2 transition-colors hover:border-outline-gray-4'
					: 'border-dashed border-outline-gray-3 pointer-events-none'
			"
		>
			<!-- icon and badge header -->
			<div class="flex items-start justify-between gap-3 mb-3">
				<div class="grid size-8 place-items-center rounded-5 bg-surface-gray-2">
					<span :class="service.icon" class="size-4 text-ink-gray-6" />
				</div>
				<Badge v-if="!service.live" label="Coming soon" />
				<Badge
					v-else
					:theme="service.on ? 'green' : 'gray'"
					:label="service.on ? 'On' : 'Off'"
				/>
			</div>

			<p class="text-base-medium text-ink-gray-9">{{ service.title }}</p>
			<p class="mt-1 text-p-base text-ink-gray-5 mb-3">
				{{ service.description }}
			</p>

			<div class="mt-auto flex items-center gap-2 text-p-base">
				<span :class="service.on ? 'text-ink-gray-7' : 'text-ink-gray-5'">
					{{ service.meta }}
				</span>

				<span
					v-if="service.to"
					class="lucide-arrow-right ml-auto size-4 text-ink-gray-5"
				/>
			</div>
		</router-link>
	</section>
</template>
