<script setup lang="ts">
import { computed } from 'vue'
import { Badge, useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'

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

const services = computed(() => [
	{
		icon: 'sparkles',
		title: 'AI inference',
		description:
			'Open models on Frappe hardware, through an OpenAI-compatible API.',
		costValue: aiUsage.value ?? '—',
		costSuffix: 'this cycle',
		to: '/addons/ai',
		disabled: false,
	},
	{
		icon: 'archive',
		title: 'Object storage',
		description:
			'S3-compatible buckets for file uploads, backups and static assets.',
		costValue: '$2',
		costSuffix: 'per GB-month · downloads are free',
		to: '/addons/object-storage',
		disabled: true,
	},
	{
		icon: 'mail',
		title: 'Email sending',
		description:
			'Send mail from your own domain. DKIM and SPF handled for you.',
		costValue: '$752',
		costSuffix: 'this cycle',
		to: '/addons/email-sending',
		disabled: true,
	},
	{
		icon: 'file-text',
		title: 'PDF rendering',
		description: 'PDFs from your print formats, rendered off your server.',
		costValue: '1,000 free',
		costSuffix: 'then $0.20 per document',
		to: '/addons/pdf-rendering',
		disabled: true,
	},
])
</script>

<template>
	<div class="flex flex-col gap-3 leading-relaxed max-w-3xl mx-auto mt-10 px-5">
		<h2 class="text-xl">Add-on services</h2>
		<p class="-mt-2 text-ink-gray-5">
			Pay for what you use, not a monthly fee.
		</p>

		<div class="flex gap-3 items-center rounded bg-surface-gray-1 p-2 px-3">
			<span>$1,789 </span>
			<span class="text-ink-gray-5 mr-auto"> this cycle . 2 of 4 on </span>

			<router-link class="text-ink-gray-6" to="/billing/invoices"
				>See on billing</router-link
			>
		</div>

		<section class="grid md:grid-cols-2 gap-3 mt-5">
			<router-link
				v-for="service in services"
				:key="service.title"
				:to="service.disabled ? '' : service.to"
				class="p-4 rounded-lg flex flex-col gap-3 border border-outline-gray-2 transition-all duration-300 hover:border-outline-gray-6"
				:class="service.disabled ? 'opacity-50' : ''"
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
						{{ service.disabled ? 'Off' : 'On' }}
					</Badge>
				</div>

				<span class="font-medium">{{ service.title }}</span>

				<p class="text-ink-gray-5">
					{{ service.description }}
				</p>

				<div class="flex items-center">
					<span>{{ service.costValue }} </span>
					<span class="text-ink-gray-5 ml-1"> {{ service.costSuffix }}</span>

					<lucide-arrow-right class="size-4 ml-auto" />
				</div>
			</router-link>
		</section>
	</div>
</template>
