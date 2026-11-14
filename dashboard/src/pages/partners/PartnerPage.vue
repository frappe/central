<script setup lang="ts">
import { Avatar, Button, ErrorMessage, LoadingText } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import AddPartnerDialog from '@/components/partners/AddPartnerDialog.vue'
import EndPartnerLinkDialog from '@/components/partners/EndPartnerLinkDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useOnboarding } from '@/composables/useOnboarding'
import {
	usePartnerLinkIntent,
	useTeamPartner,
} from '@/composables/usePartnerLinks'
import { useSession } from '@/composables/useSession'
import { formatDate } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { PartnerLink } from '@/types/api'

const session = useSession()
const intent = usePartnerLinkIntent()
const { pendingSteps } = useOnboarding()
const { canManagePartners } = useCapabilities()
const { link, loading, error, reload } = useTeamPartner()

const adding = ref(false)
const ending = ref<PartnerLink | null>(null)

// A Connect link for a team still in onboarding adds the partner there. A team that has
// finished onboarding gets the dialog here.
const isLinkWaiting = computed(() => {
	const team = session.teams.value.find(
		(option) => option.name === session.activeTeam.value,
	)
	return (
		Boolean(intent.code.value) &&
		Boolean(team) &&
		!team?.has_partner &&
		!pendingSteps.value.length
	)
})
watch(
	isLinkWaiting,
	(isWaiting) => {
		if (isWaiting) adding.value = true
	},
	{ immediate: true },
)
watch(adding, (isOpen) => {
	if (!isOpen && intent.code.value) intent.clear()
})

function onChanged(): void {
	session.reload()
	reload()
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<main class="mx-auto flex max-w-3xl flex-col gap-4 p-3 md:p-4 lg:mt-6">
			<div>
				<h1 class="text-lg-semibold text-ink-gray-9">{{ __('Partner') }}</h1>
				<p class="mt-0.5 text-p-base text-ink-gray-5">
					{{ __('The Frappe partner that works with your team.') }}
				</p>
			</div>

			<LoadingText v-if="loading && !link" :text="__('Loading partner')" />

			<div v-else-if="error" class="space-y-3">
				<ErrorMessage :message="error" />
				<Button :label="__('Try again')" @click="reload" />
			</div>

			<div
				v-else-if="link"
				class="flex items-center gap-3 rounded-6 border border-outline-gray-2 p-4"
			>
				<Avatar
					:image="link.partner_logo ?? undefined"
					:label="link.partner_name"
					size="2xl"
					shape="square"
				/>
				<div class="min-w-0 flex-1">
					<p class="truncate text-base-medium text-ink-gray-9">
						{{ link.partner_name }}
					</p>
					<p class="mt-0.5 text-p-sm text-ink-gray-5">
						{{ __('Partner since {0}', [formatDate(link.linked_on)]) }}
					</p>
				</div>
				<Button
					v-if="canManagePartners"
					theme="red"
					:label="__('End link')"
					@click="ending = link"
				/>
			</div>

			<EmptyState
				v-else
				icon="lucide-handshake"
				:title="__('No partner yet')"
				:description="__('A Frappe partner can build and run your systems. Add one with the code they gave you.')"
			>
				<template v-if="canManagePartners" #action>
					<Button
						variant="solid"
						:label="__('Add partner')"
						@click="adding = true"
					/>
				</template>
			</EmptyState>
		</main>

		<AddPartnerDialog
			v-model:open="adding"
			:initial-code="intent.code.value"
			:reference="intent.reference.value"
			@added="onChanged"
		/>
		<EndPartnerLinkDialog
			v-model:target="ending"
			:other-team-name="link?.partner_name ?? ''"
			@ended="onChanged"
		/>
	</div>
</template>
