<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from 'frappe-ui'
import OnboardingSection from '@/components/onboarding/OnboardingSection.vue'
import { ONBOARDING_STEPS } from '@/onboarding/steps'

// First-run billing setup, rendered as an accordion of collapsible sections driven
// entirely by the ONBOARDING_STEPS registry. Each section reports its own
// completion (v-model:complete); a section stays LOCKED — collapsed and
// non-interactive — until every preceding non-optional step is complete. The open
// section follows the first incomplete, unlocked step unless the team manually
// opens another. Adding a step is a registry-only change (see onboarding/steps.js).
//
// Navigation stays open elsewhere; money-moving actions divert here via
// useBillingSetup.requireSetup(), passing a ?redirect= that finish() returns to.
const route = useRoute()
const router = useRouter()
const steps = ONBOARDING_STEPS

const done = reactive(Object.fromEntries(steps.map((s) => [s.key, false])))

// A step is locked until every preceding NON-optional step is complete.
function locked(i) {
  return steps.slice(0, i).some((s) => !s.optional && !done[s.key])
}
function stateOf(i) {
  if (done[steps[i].key]) return 'complete'
  return locked(i) ? 'locked' : 'active'
}

// The open section follows the first incomplete, unlocked step — unless the team
// manually toggles one (manualKey), which we respect until the next advance.
const manualKey = ref(undefined)
const autoKey = computed(() => {
  const i = steps.findIndex((s, idx) => !done[s.key] && !locked(idx))
  return i === -1 ? null : steps[i].key
})
const openKey = computed(() => (manualKey.value !== undefined ? manualKey.value : autoKey.value))

function toggle(i) {
  if (locked(i)) return
  manualKey.value = openKey.value === steps[i].key ? null : steps[i].key
}
function onComplete(key, val) {
  done[key] = val
}
function onAdvance() {
  manualKey.value = undefined // hand control back to autoKey → opens the next step
}

const completedCount = computed(() => steps.filter((s) => done[s.key]).length)
const requiredDone = computed(() => steps.every((s) => s.optional || done[s.key]))
const allDone = computed(() => completedCount.value === steps.length)

// Leave the wizard for wherever the team was headed (or the dashboard).
function finish() {
  router.replace(route.query.redirect || '/billing')
}
</script>

<template>
  <div class="h-full overflow-y-auto bg-surface-gray-1">
    <div class="mx-auto w-full max-w-2xl px-5 py-10">
      <header class="mb-6">
        <h1 class="text-xl text-ink-gray-9">Set up billing for your team</h1>
        <p class="mt-1 text-p-base text-ink-gray-6">
          A couple of quick steps and you’re ready to add credits, a payment method, and
          provision resources.
        </p>

        <div class="mt-4 flex items-center gap-3">
          <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-gray-3">
            <div
              class="h-full rounded-full bg-surface-green-5 transition-all duration-500 ease-out"
              :style="{ width: `${(completedCount / steps.length) * 100}%` }"
            />
          </div>
          <span class="shrink-0 text-p-sm text-ink-gray-5">
            {{ completedCount }} of {{ steps.length }} done
          </span>
        </div>
      </header>

      <div class="space-y-3">
        <OnboardingSection
          v-for="(s, i) in steps"
          :key="s.key"
          :index="i"
          :title="s.title"
          :description="s.description"
          :optional="s.optional"
          :state="stateOf(i)"
          :open="openKey === s.key"
          @toggle="toggle(i)"
        >
          <component
            :is="s.component"
            :active="openKey === s.key"
            :complete="done[s.key]"
            @update:complete="onComplete(s.key, $event)"
            @advance="onAdvance"
          />
        </OnboardingSection>
      </div>

      <div class="mt-6 flex items-center justify-between gap-3">
        <p class="text-p-sm text-ink-gray-5">
          <template v-if="allDone">You’re all set.</template>
          <template v-else-if="requiredDone">Optional steps left — head to the dashboard whenever you’re ready.</template>
          <template v-else>Complete the required step to continue.</template>
        </p>
        <Button
          variant="solid"
          label="Go to dashboard"
          :disabled="!requiredDone"
          @click="finish"
        />
      </div>
    </div>
  </div>
</template>
