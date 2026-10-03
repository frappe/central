<script setup lang="ts">
import { Alert, Button, Dialog } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type {
	OnboardingStep,
	OnboardingStepHandle,
} from '@/components/onboarding/steps'
import { useOnboarding } from '@/composables/useOnboarding'
import { getErrorMessage } from '@/lib/feedback'

// The dialog orders the steps, moves between them, and records each answer. Every
// step saves its own work. It cannot be dismissed: the owner finishes or skips it.
const router = useRouter()
const { pendingSteps, answerStep, skipAll, reload } = useOnboarding()

const open = ref(false)
const steps = ref<OnboardingStep[]>([])
const index = ref(0)
const stepHandle = ref<OnboardingStepHandle | null>(null)
const busy = ref(false)
const error = ref('')

const current = computed(() => steps.value[index.value])
const isLast = computed(() => index.value === steps.value.length - 1)
const canSkip = computed(() => !current.value?.isRequired && !isLast.value)

// Take the steps once when the dialog opens, so an answer does not reorder the rest.
watch(
	pendingSteps,
	(pending) => {
		if (open.value || !pending.length) return
		steps.value = pending
		index.value = 0
		open.value = true
	},
	{ immediate: true },
)

async function runPrimary(): Promise<void> {
	const handle = stepHandle.value
	if (!handle?.canSubmit || handle.saving || busy.value) return
	if (await handle.submit()) await advance('Done')
}

async function advance(status: 'Done' | 'Skipped'): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		const step = current.value
		// A new team brings its own stored steps. The team step itself is not stored.
		if (step.key === 'team') steps.value = [step, ...pendingSteps.value]
		else await answerStep(step.key, status)

		if (isLast.value) await finish()
		else index.value += 1
	} catch (exception) {
		error.value = getErrorMessage(exception)
	} finally {
		busy.value = false
	}
}

async function finish(): Promise<void> {
	await reload()
	open.value = false
	await router.push('/servers')
}

async function skipOnboarding(): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		await skipAll()
		open.value = false
	} catch (exception) {
		error.value = getErrorMessage(exception)
	} finally {
		busy.value = false
	}
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
				<!-- Every step gets the same height, so the dialog never resizes between
             steps or while a step loads. A longer step scrolls inside it. -->
				<div class="-mx-1 mt-4 h-96 overflow-y-auto px-1">
					<component
						:is="current.component"
						ref="stepHandle"
						@submit="runPrimary"
					/>
				</div>
			</div>
		</Transition>

		<template #actions>
			<div class="flex w-full items-center justify-between gap-2">
				<Button
					v-if="canSkip"
					variant="ghost"
					label="Skip onboarding"
					:disabled="busy"
					@click="skipOnboarding"
				/>
				<span v-else />

				<div class="flex gap-2">
					<Button
						v-if="canSkip"
						label="Skip for now"
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
