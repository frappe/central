<script setup lang="ts">
import { Badge, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { features } from '@/lib/features'

interface MeteredRow {
	resource_type: string | null
	unit: string | null
	period_usage: number
}

const { activeTeam } = useSession()

const metered = useCall<{ services: MeteredRow[] }, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => metered.reload())

const aiUsage = computed(() => {
	const row = metered.data?.services.find((s) => s.resource_type === 'Tokens')
	if (!row) return null
	return `${new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(row.period_usage)} ${row.unit || 'tokens'}`
})

// A service's "On"/"Coming soon" state is its rollout flag (Central Settings),
// not the billing catalogue. Live cards show real usage only — no placeholder
// pricing. A card with no usage source yet shows an em dash, never a made-up figure.
const services = computed(() => [
	{
		icon: 'sparkles',
		title: 'AI inference',
		description:
			'Open models on Frappe hardware, through an OpenAI-compatible API.',
		usage: aiUsage.value ?? '—',
		to: '/addons/ai',
		enabled: features.llm,
	},
	{
		icon: 'archive',
		title: 'Object storage',
		description:
			'S3-compatible buckets for file uploads, backups and static assets.',
		usage: '—',
		to: '/addons/object-storage',
		enabled: features.storage,
	},
	{
		icon: 'mail',
		title: 'Email sending',
		description:
			'Send mail from your own domain. DKIM and SPF handled for you.',
		usage: '—',
		to: '/addons/email-sending',
		enabled: features.email,
	},
	{
		icon: 'file-text',
		title: 'PDF rendering',
		description: 'PDFs from your print formats, rendered off your server.',
		usage: '—',
		to: '/addons/pdf-rendering',
		enabled: features.pdf,
	},
])

const enabledCount = computed(() => services.value.filter((s) => s.enabled).length)
</script>

<template>
	<div class="flex flex-col gap-3 leading-relaxed max-w-3xl mx-auto mt-10 px-5">
		<h2 class="text-xl">Add-on services</h2>
		<p class="-mt-2 text-ink-gray-5">
			Pay for what you use, not a monthly fee.
		</p>

		<div class="flex gap-3 items-center rounded bg-surface-gray-1 p-2 px-3">
			<span class="text-ink-gray-5 mr-auto">
				{{ enabledCount }} of {{ services.length }} available
			</span>

			<router-link class="text-ink-gray-6" to="/billing/invoices"
				>See on billing</router-link
			>
		</div>

		<section class="grid md:grid-cols-2 gap-3 mt-5">
			<component
				:is="service.enabled ? 'router-link' : 'div'"
				v-for="service in services"
				:key="service.title"
				:to="service.enabled ? service.to : undefined"
				class="p-4 rounded-lg flex flex-col gap-3 border border-outline-gray-2 transition-all duration-300"
				:class="
					service.enabled ? 'hover:border-outline-gray-6' : 'opacity-50'
				"
			>
				<div class="flex items-center gap-3">
					<div class="bg-surface-gray-1 rounded-lg p-2">
						<lucide-sparkles
							v-if="service.icon === 'sparkles'"
							class="size-6 text-ink-gray-5"
						/>
						<lucide-archive
							v-else-if="service.icon === 'archive'"
							class="size-6 text-ink-gray-5"
						/>
						<lucide-mail
							v-else-if="service.icon === 'mail'"
							class="size-6 text-ink-gray-5"
						/>
						<lucide-file-text
							v-else-if="service.icon === 'file-text'"
							class="size-6 text-ink-gray-5"
						/>
					</div>

					<Badge class="ml-auto mb-auto">
						{{ service.enabled ? 'On' : 'Coming soon' }}
					</Badge>
				</div>

				<span class="font-medium">{{ service.title }}</span>

				<p class="text-ink-gray-5">
					{{ service.description }}
				</p>

				<div v-if="service.enabled" class="flex items-center">
					<span>{{ service.usage }} </span>
					<span class="text-ink-gray-5 ml-1"> this cycle</span>

					<lucide-arrow-right class="size-4 ml-auto" />
				</div>
			</component>
		</section>
	</div>
</template>
