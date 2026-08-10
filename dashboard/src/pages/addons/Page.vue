<script setup lang="ts">
import { Badge, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
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

// The catalog is product copy; whether a service is rolled out comes from the
// Central Settings feature flags, and what it costs and has used comes from the
// API. `resourceType` is the join key. Every service names the page it will
// own — see `linkable` below.
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
		to: '/addons/pdf-rendering',
		flag: 'pdf' as const,
	},
	{
		resourceType: 'Emails',
		icon: 'lucide-mail',
		title: 'Email sending',
		description:
			'Send mail from your own domain. DKIM and SPF handled for you.',
		noun: 'emails',
		to: '/addons/email-sending',
		flag: 'email' as const,
	},
]

// A card turns into a link the moment its route exists — registering the route
// is the only step. Asking the router beats a hand-kept flag here, which would
// be a second place to remember and a dead link when someone forgets.
const router = useRouter()
const isRouted = (to: string): boolean =>
	router.resolve(to).matched.length > 0

const number = new Intl.NumberFormat(undefined, {
	notation: 'compact',
	maximumFractionDigits: 1,
})

// Per-unit rates run to five decimals, so quote them per thousand — $0.22 per
// 1,000 documents reads where $0.00022 each does not.
function rateLabel(rate: number, noun: string): string {
	return `${money(rate * 1000, currency.value)} per 1,000 ${noun}`
}

const cards = computed(() =>
	CATALOG.map((entry) => {
		// Off flag = not rolled out yet, whatever the catalog or a seeded
		// subscription says.
		const comingSoon = !features[entry.flag]
		const subscribed = metered.data?.services.find(
			(s) => s.resource_type === entry.resourceType,
		)
		const plan = metered.data?.available_plans.find(
			(p) => p.resource_type === entry.resourceType,
		)
		const rate = subscribed?.locked_rate ?? plan?.rate
		return {
			...entry,
			comingSoon,
			on: !!subscribed,
			linkable: !comingSoon && isRouted(entry.to),
			// Coming soon: what it will cost. On: what it has done this cycle.
			// Off: what it would cost.
			meta: comingSoon
				? rate
					? rateLabel(rate, entry.noun)
					: 'Pricing to be announced'
				: subscribed
					? subscribed.period_usage
						? `${number.format(subscribed.period_usage)} ${entry.noun} this cycle`
						: 'No usage this cycle'
					: rate
						? rateLabel(rate, entry.noun)
						: 'Not available yet',
		}
	}),
)
</script>

<template>
	<div class="mx-auto mt-10 max-w-3xl px-5">
		<section class="grid gap-3 md:grid-cols-2">
			<!-- A card is a link only once its page exists, so nothing invites a
			     click that goes nowhere. -->
			<component
				:is="service.linkable ? 'router-link' : 'div'"
				v-for="service in cards"
				:key="service.title"
				:to="service.linkable ? service.to : undefined"
				class="flex flex-col gap-3 rounded-lg border p-4"
				:class="[
					service.comingSoon
						? 'border-dashed border-outline-gray-3'
						: 'border-outline-gray-2',
					service.linkable ? 'transition-colors hover:border-outline-gray-4' : '',
				]"
			>
				<div class="flex items-start justify-between gap-3">
					<div class="grid size-8 place-items-center rounded-md bg-surface-gray-2">
						<span :class="service.icon" class="size-4 text-ink-gray-6" />
					</div>
					<Badge
						v-if="service.comingSoon"
						theme="gray"
						variant="subtle"
						label="Coming soon"
					/>
					<Badge
						v-else
						:theme="service.on ? 'green' : 'gray'"
						variant="subtle"
						:label="service.on ? 'On' : 'Off'"
					/>
				</div>

				<div>
					<p class="text-base-medium text-ink-gray-9">{{ service.title }}</p>
					<p class="mt-1 text-p-base text-ink-gray-5">
						{{ service.description }}
					</p>
				</div>

				<div class="mt-auto flex items-center gap-2 text-p-base">
					<span :class="service.on ? 'text-ink-gray-7' : 'text-ink-gray-5'">
						{{ service.meta }}
					</span>
					<span
						v-if="service.linkable"
						class="lucide-arrow-right ml-auto size-4 text-ink-gray-5"
						aria-hidden="true"
					/>
				</div>
			</component>
		</section>
	</div>
</template>
