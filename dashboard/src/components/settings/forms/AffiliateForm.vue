<script setup lang="ts">
import {
	Alert,
	Button,
	Divider,
	SettingsRow,
	Skeleton,
	Switch,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import AffiliateLinkBox from '@/components/affiliate/AffiliateLinkBox.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAffiliate } from '@/composables/useAffiliate'
import { closeSettings } from '@/composables/useSettings'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import { router } from '@/router'

const {
	affiliate,
	cookieDays,
	isJoined,
	isPausedByFrappe,
	loading,
	error,
	saving,
	reload,
	setJoined,
} = useAffiliate()

const saveError = ref('')
// Leaving asks first. The switch stays on until the person confirms.
const confirmingLeave = ref<true | null>(null)
const leaveError = ref('')

const features = computed(() => [
	{
		icon: 'lucide-link',
		title: __('One link for every product'),
		description: __(
			'Send people to Frappe Cloud or any product, and name each post or video with a campaign.',
		),
	},
	{
		icon: 'lucide-chart-column-increasing',
		title: __('See what works'),
		description: __(
			'Signups and paying customers by source, campaign and product.',
		),
	},
	{
		icon: 'lucide-cookie',
		title: __('{0} days to sign up', [cookieDays.value]),
		description: __(
			'People who click your link and sign up within {0} days count for you.',
			[cookieDays.value],
		),
	},
	{
		icon: 'lucide-eye-off',
		title: __('Counts, never names'),
		description: __('You never see who signed up, only how many.'),
	},
])

async function toggle(joined: boolean): Promise<void> {
	saveError.value = ''
	if (!joined) {
		leaveError.value = ''
		confirmingLeave.value = true
		return
	}

	try {
		await setJoined(true)
		successToast(__('You are now an affiliate.'))
	} catch (failure) {
		saveError.value = getErrorMessage(
			failure,
			__("You couldn't join the affiliate program. Try again."),
		)
	}
}

async function leave(): Promise<void> {
	try {
		await setJoined(false)
		confirmingLeave.value = null
	} catch (failure) {
		// The dialog stays open, with the reason inside it.
		leaveError.value = getErrorMessage(
			failure,
			__("You couldn't leave the affiliate program. Try again."),
		)
	}
}

function openAffiliatePage(): void {
	closeSettings()
	router.push('/affiliate')
}
</script>

<template>
	<div class="mt-6" data-affiliate-form>
		<EmptyState
			v-if="error && cookieDays === null"
			icon="lucide-cloud-off"
			:title="__('The affiliate program couldn\'t load')"
			:description="getErrorMessage(error, __('Try again in a moment.'))"
		>
			<template #action>
				<Button :label="__('Retry')" @click="reload" />
			</template>
		</EmptyState>

		<div v-else-if="cookieDays === null" class="space-y-2" aria-busy="true">
			<Skeleton v-for="row in 3" :key="row" class="h-14 rounded-6" />
		</div>

		<template v-else>
			<Alert
				v-if="saveError"
				class="mb-4"
				theme="red"
				:title="__('Affiliate program not changed')"
				:description="saveError"
			/>

			<SettingsRow
				class="!items-start !py-0"
				:title="__('Join the affiliate program')"
				:description="
					__(
						'You get a link right away. Affiliate shows in your sidebar while you are in the program.',
					)
				"
			>
				<Switch
					:model-value="isJoined"
					:disabled="saving || loading || isPausedByFrappe"
					@update:model-value="toggle"
				/>
			</SettingsRow>

			<Alert
				v-if="isPausedByFrappe"
				class="mt-4"
				theme="amber"
				:title="__('Frappe paused your affiliate link')"
				:description="__('Contact support to turn it on again.')"
			/>

			<Divider class="my-6" />

			<template v-if="isJoined && affiliate">
				<AffiliateLinkBox :link="affiliate.link" :label="__('Your link')" />

				<Button
					class="mt-4"
					variant="solid"
					icon-right="lucide-arrow-right"
					:label="__('Make links and see performance')"
					@click="openAffiliatePage"
				/>
			</template>

			<ul v-else class="space-y-5">
				<li v-for="feature in features" :key="feature.icon" class="flex gap-3">
					<span
						:class="[feature.icon, 'mt-0.5 size-4 shrink-0 text-ink-gray-6']"
						aria-hidden="true"
					/>
					<div>
						<p class="text-base-medium text-ink-gray-8">{{ feature.title }}</p>
						<p class="mt-1 text-p-sm text-ink-gray-6">
							{{ feature.description }}
						</p>
					</div>
				</li>
			</ul>
		</template>

		<ConfirmDialog
			v-model:target="confirmingLeave"
			:title="__('Leave the affiliate program?')"
			:message="
				__(
					'Your links stop counting new signups. The signups you already brought stay counted, and you can join again.',
				)
			"
			:confirm-label="__('Leave')"
			size="md"
			:loading="saving"
			:error="leaveError"
			@confirm="leave"
		/>
	</div>
</template>

<style scoped>
/* SettingsRow descriptions read at 13px on this tab only. */
[data-affiliate-form] :deep(.text-base.text-ink-gray-6) {
	@apply text-p-sm;
}
</style>
