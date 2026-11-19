import { computed, type Ref, ref } from 'vue'
import { __ } from '@/lib/translate'
import type {
	NotificationCategory as Category,
	NotificationCatalogEvent,
} from '@/types/billing'

export type Channel = 'email' | 'in_app'

interface ChannelOffOptions {
	state: Record<Category, Record<Channel, boolean>>
	eventsOf: (category: Category) => NotificationCatalogEvent[]
	labelOf: (category: Category) => string
	isTeamOwner: Ref<boolean>
}

/** Asks before a channel with critical events turns off, and words what the user will miss. */
export function useChannelOffConfirm({
	state,
	eventsOf,
	labelOf,
	isTeamOwner,
}: ChannelOffOptions) {
	const offTarget = ref<{ category: Category; channel: Channel } | null>(null)

	const offCriticalEvents = computed(() =>
		offTarget.value
			? eventsOf(offTarget.value.category).filter((event) => event.is_critical)
			: [],
	)
	const offTitle = computed(() => {
		if (!offTarget.value) return ''
		const { category, channel } = offTarget.value
		return channel === 'email'
			? __('Turn off {0} emails?', [labelOf(category)])
			: __('Turn off {0} in-app notifications?', [labelOf(category)])
	})
	const isLastChannel = computed(() => {
		if (!offTarget.value || isTeamOwner.value) return false
		const { category, channel } = offTarget.value
		return !state[category][channel === 'email' ? 'in_app' : 'email']
	})
	const offMessage = computed(() => {
		const isEmail = offTarget.value?.channel === 'email'
		if (isTeamOwner.value)
			return isEmail
				? __(
						'Regular emails stop. As the team owner, you still get these critical events by email:',
					)
				: __(
						'Regular notifications stop showing in the app. As the team owner, you still see these critical events:',
					)
		return isEmail
			? __('These critical events also stop reaching you by email:')
			: __('These critical events also stop showing in the app:')
	})
	const offNote = computed(() => {
		if (isTeamOwner.value || isLastChannel.value) return ''
		return offTarget.value?.channel === 'email'
			? __('You still see them in the app.')
			: __('You still get them by email.')
	})

	function setChannel(category: Category, channel: Channel, on: boolean) {
		if (on || !eventsOf(category).some((event) => event.is_critical)) {
			state[category][channel] = on
			return
		}
		offTarget.value = { category, channel }
	}

	function confirmOff(target: { category: Category; channel: Channel }) {
		state[target.category][target.channel] = false
		offTarget.value = null
	}

	return {
		offTarget,
		offCriticalEvents,
		offTitle,
		isLastChannel,
		offMessage,
		offNote,
		setChannel,
		confirmOff,
	}
}
