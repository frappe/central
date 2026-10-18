<script setup lang="ts">
import { Avatar, Button } from 'frappe-ui'
import { computed } from 'vue'
import ChoiceCards, { type Choice } from '@/components/common/ChoiceCards.vue'
import type { PartnerSetupTeam } from '@/types/api'

interface Props {
	modelValue: string | null
	teams: PartnerSetupTeam[]
	partnerName: string
	/** `link` picks the account a partner works with, `register` the partner's own team. */
	purpose?: 'link' | 'register'
	canCreate?: boolean
}

const props = withDefaults(defineProps<Props>(), {
	purpose: 'link',
	canCreate: true,
})

const emit = defineEmits<{
	'update:modelValue': [team: string]
	create: []
}>()

const options = computed<Choice[]>(() =>
	props.teams.map((team) => ({
		label: team.label,
		value: team.name,
		description: describe(team),
		disabled: !team.available,
	})),
)

function logoOf(name: string): string | undefined {
	return props.teams.find((team) => team.name === name)?.logo ?? undefined
}

function describe(team: PartnerSetupTeam): string {
	if (props.purpose === 'register') return describeForRegistration(team)
	switch (team.reason) {
		case 'partner_team':
			return 'This is a partner’s own account.'
		case 'linked_to_this_partner':
			// A Connect hire takes the earlier link over, so the team stays available.
			return team.available
				? `Works with ${props.partnerName} already. This hire takes that over.`
				: `Already works with ${props.partnerName}.`
		case 'linked_to_another_partner':
			return `Works with ${team.current_partner}. An account has one partner at a time.`
		case 'cannot_manage':
			return `Only its owner or an admin can add a partner. Ask ${team.owner}.`
		default:
			return memberCount(team)
	}
}

function describeForRegistration(team: PartnerSetupTeam): string {
	switch (team.reason) {
		case 'partner_team':
			return 'Already a partner team.'
		case 'linked_to_this_partner':
		case 'linked_to_another_partner':
			return `Works with ${team.current_partner}, so it can’t be a partner.`
		case 'cannot_manage':
			return `Only its owner or an admin can make it a partner. Ask ${team.owner}.`
		default:
			return memberCount(team)
	}
}

function memberCount(team: PartnerSetupTeam): string {
	return team.members === 1 ? '1 member' : `${team.members} members`
}
</script>

<template>
	<div class="space-y-2">
		<ChoiceCards
			:model-value="modelValue"
			:options="options"
			:columns="1"
			:label="purpose === 'register' ? 'Your teams' : 'Your accounts'"
			@update:model-value="emit('update:modelValue', $event)"
		>
			<template #icon="{ option }">
				<Avatar
					:image="logoOf(option.value)"
					:label="option.label"
					size="lg"
					shape="square"
				/>
			</template>
		</ChoiceCards>
		<Button
			v-if="canCreate"
			class="w-full"
			size="md"
			variant="subtle"
			:label="purpose === 'register' ? 'Create a new team' : 'Create a new account'"
			@click="emit('create')"
		>
			<template #prefix>
				<span class="lucide-plus size-4" aria-hidden="true" />
			</template>
		</Button>
	</div>
</template>
