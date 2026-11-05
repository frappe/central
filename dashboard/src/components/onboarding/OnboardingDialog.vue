<script setup lang="ts">
import { Alert, Button, Dialog } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type {
	OnboardingStep,
	OnboardingStepHandle,
} from '@/components/onboarding/steps'
import { type StepStatus, useOnboarding } from '@/composables/useOnboarding'
import { getErrorMessage } from '@/lib/feedback'

// The dialog orders the steps, moves between them, and records each answer. Every
// step saves its own work. It cannot be dismissed: the owner finishes or skips it.
const router = useRouter()
const { pendingSteps, answerStep, reload } = useOnboarding()

const open = ref(false)
const steps = ref<OnboardingStep[]>([])
const index = ref(0)
// Answers recorded in this dialog, so a step the owner goes back to is not recorded twice.
const answers = ref<Partial<Record<OnboardingStep['key'], StepStatus>>>({})
const stepHandle = ref<OnboardingStepHandle | null>(null)
const busy = ref(false)
const error = ref('')

const current = computed(() => steps.value[index.value])
const isLast = computed(() => index.value === steps.value.length - 1)
const canSkip = computed(() => !current.value?.isRequired && !isLast.value)
// The team exists once its step is done, so the owner cannot go back to it.
const canGoBack = computed(
	() => index.value > 0 && !steps.value[index.value - 1].isRequired,
)
const isAnswered = computed(
	() => !!current.value && !!answers.value[current.value.key],
)

// Take the steps once when the dialog opens, so an answer does not reorder the rest.
watch(
	pendingSteps,
	(pending) => {
		if (open.value || !pending.length) return
		steps.value = pending
		index.value = 0
		answers.value = {}
		open.value = true
	},
	{ immediate: true },
)

async function runPrimary(): Promise<void> {
	const handle = stepHandle.value
	if (!handle?.canSubmit || handle.saving || busy.value) return
	if (await handle.submit()) await advance('Done')
}

async function advance(status: StepStatus): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		await record(current.value, status)
		if (isLast.value) await finish()
		else index.value += 1
	} catch (exception) {
		error.value = getErrorMessage(exception)
	} finally {
		busy.value = false
	}
}

async function record(step: OnboardingStep, status: StepStatus): Promise<void> {
	// A new team brings its own stored steps. The team step itself is not stored.
	if (step.key === 'team') {
		steps.value = [step, ...pendingSteps.value]
		return
	}

	const previous = answers.value[step.key]
	if (previous === 'Done' || previous === status) return

	await answerStep(step.key, status)
	answers.value[step.key] = status
}

function goBack(): void {
	error.value = ''
	index.value -= 1
}

async function finish(): Promise<void> {
	await reload()
	open.value = false
	await router.push('/servers')
}
</script>

<template>
	<Dialog
		v-model:open="open"
		size="xl"
		:title="current?.title"
		:dismissible="false"
		:show-close-button="false"
	>
		<div v-if="steps.length > 1" class="mb-5 flex items-center gap-1.5">
			<span
				v-for="(step, position) in steps"
				:key="step.key"
				class="h-1 flex-1 rounded-full transition-colors"
				:class="position <= index ? 'bg-surface-gray-10' : 'bg-surface-gray-3'"
			/>
		</div>

		<Alert v-if="error" class="mb-4" theme="red" :title="error" />

		<Transition
			mode="out-in"
			enter-active-class="transition duration-150 ease-out"
			enter-from-class="translate-x-2 opacity-0"
			leave-active-class="transition duration-100 ease-in"
			leave-to-class="-translate-x-2 opacity-0"
		>
			<div v-if="current" :key="current.key">
				<p class="text-p-base text-ink-gray-6">{{ current.description }}</p>
				<!-- On a wider screen every step gets the same height, so the dialog never
             resizes between steps. A phone lets the step grow, so nothing is cut off. -->
				<div class="-mx-1 mt-4 px-1 sm:h-96 sm:overflow-y-auto">
					<component
						:is="current.component"
						ref="stepHandle"
						@submit="runPrimary"
					/>
				</div>
			</div>
		</Transition>

		<template #actions>
			<!-- Stacked on a phone, so the primary action never runs off the edge. -->
			<div
				class="flex w-full flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between"
			>
				<Button
					v-if="canGoBack"
					variant="ghost"
					icon-left="lucide-arrow-left"
					label="Back"
					:disabled="busy || stepHandle?.saving"
					@click="goBack"
				/>
				<span v-else class="hidden sm:block" />

				<div class="flex flex-col-reverse gap-2 sm:flex-row">
					<Button
						v-if="canSkip"
						:label="isAnswered ? 'Next' : 'Skip'"
						:disabled="busy || stepHandle?.saving"
						@click="advance('Skipped')"
					/>
					<Button
						variant="solid"
						:label="stepHandle?.submitLabel ?? 'Continue'"
						:loading="busy || stepHandle?.saving"
						:disabled="!stepHandle?.canSubmit"
						@click="runPrimary"
					/>
				</div>
			</div>
		</template>
	</Dialog>
</template>
