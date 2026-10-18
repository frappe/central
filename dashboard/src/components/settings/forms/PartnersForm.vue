<script setup lang="ts">
import { Alert, Avatar, Badge, Button } from 'frappe-ui'
import { ref } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Table from '@/components/common/Table.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamPartners } from '@/composables/useTeamPartners'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { formatDate } from '@/lib/format'
import type { TeamPartnerLink } from '@/types/api'

const COLUMNS = [
	{ key: 'client_name', label: 'Client', class: 'w-full max-w-0' },
	{ key: 'status', label: 'Status' },
	{ key: 'actions', label: '', class: 'w-10 pr-1' },
]

const { partners, loading, error, reload, end, setAccess } = useTeamPartners()
const { canManageBilling } = useCapabilities()
const ending = ref(false)
const actionError = ref('')

async function endLink(link: TeamPartnerLink, question: string, done: string) {
	if (!confirm(question)) return

	ending.value = true
	actionError.value = ''
	try {
		await end(link.name)
		successToast(done)
	} catch (failure) {
		actionError.value = getErrorMessage(
			failure,
			"The partner link couldn't be ended.",
		)
	} finally {
		ending.value = false
	}
}

const removePartner = (link: TeamPartnerLink) =>
	endLink(
		link,
		`Remove ${link.partner_name}? They stop working with your team, and they need a new hire on Connect to come back.`,
		`${link.partner_name} removed`,
	)

async function toggleAccess(link: TeamPartnerLink) {
	const giving = !link.partner_access
	ending.value = true
	actionError.value = ''
	try {
		await setAccess(link.name, giving)
		successToast(
			giving
				? `${link.partner_name} can now work on your servers`
				: `${link.partner_name} no longer has access`,
		)
	} catch (failure) {
		actionError.value = getErrorMessage(
			failure,
			"The partner's access couldn't be changed.",
		)
	} finally {
		ending.value = false
	}
}

function accessSummary(
	partner: TeamPartnerLink & { staff_count: number },
): string {
	if (!partner.partner_access) return 'No access'
	const people =
		partner.staff_count === 1
			? '1 person has'
			: `${partner.staff_count} people have`
	return `Partner role · ${people} access`
}

function statusLabel(link: TeamPartnerLink): string {
	if (link.status === 'Active') return 'Active'
	return link.source === 'Connect' ? 'Waiting for customer' : 'Waiting for you'
}

const getClientActions = (link: TeamPartnerLink) =>
	canManageBilling.value
		? [
				{
					label: 'Stop working with this customer',
					icon: 'lucide-circle-x',
					theme: 'red' as const,
					onClick: () =>
						endLink(
							link,
							`Stop working with ${link.client_name}? Connect shows it within a few minutes.`,
							`You stopped working with ${link.client_name}`,
						),
				},
			]
		: []
</script>

<template>
	<div class="space-y-6 pt-6">
		<Alert v-if="actionError" theme="red" :title="actionError" />

		<EmptyState
			v-if="error"
			icon="lucide-cloud-off"
			title="Partners couldn't load"
			:description="error"
		>
			<template #action>
				<Button label="Retry" @click="reload" />
			</template>
		</EmptyState>

		<EmptyState
			v-else-if="
				!loading &&
				partners &&
				!partners.partner &&
				!partners.is_partner
			"
			icon="lucide-handshake"
			title="No partner yet"
			description="When you hire a partner on Frappe Connect, you accept them here and they appear on this page."
		/>

		<template v-else-if="partners">
			<section v-if="partners.partner" class="space-y-2">
				<p class="text-sm text-ink-gray-5">Your partner</p>
				<div class="flex items-center gap-3 rounded-6 border p-3">
					<Avatar
						:image="partners.partner.partner_logo ?? undefined"
						:label="partners.partner.partner_name"
						size="xl"
						shape="square"
					/>
					<div class="min-w-0 flex-1">
						<p class="truncate text-base text-ink-gray-8">
							{{ partners.partner.partner_name }}
						</p>
						<p class="truncate text-p-sm text-ink-gray-5">
							{{ partners.partner.paid_by_partner
									? 'They pay for hosting'
									: 'You pay for hosting' }}
							· Since {{ formatDate(partners.partner.since) }}
						</p>
						<p class="truncate text-p-sm text-ink-gray-5">
							{{ accessSummary(partners.partner) }}
						</p>
					</div>
					<Button
						v-if="canManageBilling && !partners.partner.paid_by_partner"
						:label="partners.partner.partner_access ? 'Remove access' : 'Give access'"
						:loading="ending"
						@click="toggleAccess(partners.partner)"
					/>
					<Button
						v-if="canManageBilling"
						label="Remove partner"
						theme="red"
						:loading="ending"
						@click="removePartner(partners.partner)"
					/>
				</div>
			</section>

			<section v-if="partners.is_partner" class="space-y-2">
				<p class="text-sm text-ink-gray-5">Clients</p>
				<p v-if="!partners.clients.length" class="text-p-base text-ink-gray-6">
					No clients yet. Customers who hire you on Connect appear here once
					they accept you.
				</p>
				<Table
					v-else
					:columns="COLUMNS"
					:rows="partners.clients"
					height="h-auto"
				>
					<template #client_name="{ row }">
						<div class="space-y-1 py-2">
							<p class="truncate text-base text-ink-gray-8">
								{{ row.client_name }}
							</p>
							<p class="truncate text-sm text-ink-gray-5">
								{{ row.project_title || 'Partner code' }}
								· {{ row.paid_by_partner ? 'You pay' : 'They pay' }}
							</p>
						</div>
					</template>

					<template #status="{ row }">
						<Badge
							:theme="row.status === 'Active' ? 'green' : 'orange'"
							:label="statusLabel(row)"
						/>
					</template>

					<template #actions="{ row }">
						<RowActionsMenu
							:options="getClientActions(row)"
							label="Client actions"
							:busy="ending"
						/>
					</template>
				</Table>
			</section>
		</template>
	</div>
</template>
