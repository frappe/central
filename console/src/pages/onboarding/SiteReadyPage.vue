<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Button, ErrorMessage } from 'frappe-ui'
import { useRoute } from 'vue-router'
import MinimalAuthShell from '@/components/auth/MinimalAuthShell.vue'
import RegionMap from '@/components/onboarding/RegionMap.vue'
import { API } from '@/api/methods'
import { frappeErrorMessage, getFrappe, methodUrl } from '@/lib/auth'
import { productInfo } from '@/lib/products'
import { regionInfo } from '@/lib/regions'

type SiteState = {
  name: string
  status: string
  url: string | null
  login_url: string | null
}

// Mirrors the backend's terminal set; any terminal status that isn't Running is a failure.
const TERMINAL = new Set(['Running', 'Failed', 'Terminated'])
const POLL_MS = 3000
// A transient network blip shouldn't abort the poll during the ~15s provisioning window.
const MAX_POLL_FAILURES = 3
// The "Installing" line gets a beat on screen, then a shorter beat on the ready
// confirmation, before we hand the tenant off to their site.
const INSTALL_BEAT_MS = 1800
const READY_BEAT_MS = 1400
const CREEP_MS = 800
// Progress target per phase; the creep drifts toward it between polls.
const TARGETS: Record<string, number> = { server: 45, site: 78, install: 94 }

const route = useRoute()
const name = String(route.params.name ?? '')
const product = computed(() => {
  const slug = route.query.product
  return typeof slug === 'string' ? productInfo(slug) : null
})

// The map is decorative: get_site doesn't report a region, so it always renders the
// default location as ambiance while the site provisions.
const region = regionInfo(null)

const site = ref<SiteState | null>(null)
const error = ref('')
const installing = ref(false)
const revealed = ref(false)
const signInFailed = ref(false)
const progress = ref(6)
let pollFailures = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined
let creepTimer: ReturnType<typeof setInterval> | undefined
let revealTimer: ReturnType<typeof setTimeout> | undefined

const isReady = computed(() => revealed.value && site.value?.status === 'Running')
const isFailed = computed(
  () => !!site.value && site.value.status !== 'Running' && TERMINAL.has(site.value.status),
)

const phase = computed(() => {
  if (installing.value) return 'install'
  return site.value?.status === 'Deploying' ? 'site' : 'server'
})

const statusLine = computed(() => {
  if (phase.value === 'server') return `Setting up your private server in ${region.city}...`
  if (phase.value === 'site') return `Creating ${name} on it...`
  return product.value ? `Installing ${product.value.name}...` : 'Putting on the finishing touches...'
})

async function poll() {
  try {
    const result = await getFrappe<SiteState>(methodUrl(API.getSite), { name })
    pollFailures = 0
    site.value = result
    if (result.status === 'Running') return becomeReady()
    // Failed or Terminated: stop polling; isFailed drives the error screen.
    if (TERMINAL.has(result.status)) return
  } catch (exception) {
    pollFailures += 1
    if (pollFailures >= MAX_POLL_FAILURES) {
      error.value = frappeErrorMessage(exception, 'Lost track of your site. Refresh to retry.')
      return
    }
  }
  pollTimer = setTimeout(poll, POLL_MS)
}

// Site is up: hold on the install beat with a full bar, show the ready confirmation,
// then hand off. The handoff is the one-click login URL — navigating there lands the
// tenant inside their site, already signed in as Administrator.
function becomeReady() {
  installing.value = true
  progress.value = 100
  revealTimer = setTimeout(reveal, INSTALL_BEAT_MS)
}

function reveal() {
  revealed.value = true
  revealTimer = setTimeout(signIn, READY_BEAT_MS)
}

function signIn() {
  if (site.value?.login_url) window.location.assign(site.value.login_url)
  else signInFailed.value = true
}

function creep() {
  const target = TARGETS[phase.value] ?? 94
  if (progress.value < target) progress.value += (target - progress.value) * 0.12 + 0.3
}

onMounted(() => {
  poll()
  creepTimer = setInterval(creep, CREEP_MS)
})
onUnmounted(() => {
  clearTimeout(pollTimer)
  clearTimeout(revealTimer)
  clearInterval(creepTimer)
})
</script>

<template>
  <MinimalAuthShell>
    <template v-if="isFailed">
      <h1 class="text-xl font-semibold text-ink-gray-8">Setup didn't finish</h1>
      <p class="mt-1 text-p-sm text-ink-gray-5">
        Something went wrong provisioning your site. You can try a different name.
      </p>
      <RouterLink to="/onboarding/site" class="mt-6 block">
        <Button variant="solid" size="md" class="w-full">Try again</Button>
      </RouterLink>
    </template>

    <template v-else>
      <RegionMap :region="region" :ready="isReady" />

      <Transition name="status-swap" mode="out-in">
        <div v-if="isReady && site" key="ready" class="mt-6">
          <h1 class="text-xl font-semibold text-ink-gray-8">{{ name }} is ready</h1>
          <p v-if="!signInFailed" class="mt-1 text-p-sm text-ink-gray-5">
            Signing you in as <span class="font-medium text-ink-gray-7">Administrator</span>...
          </p>
          <p v-else class="mt-1 text-p-sm text-ink-gray-5">
            We couldn't sign you in automatically. Head to your site to log in.
          </p>

          <div v-if="!signInFailed" class="mt-6 flex items-center gap-2 text-p-base text-ink-gray-7">
            <span
              class="lucide-loader-circle size-4 shrink-0 animate-spin text-ink-gray-5"
              aria-hidden="true"
            />
            <span>Taking you to your site...</span>
          </div>
          <a v-else-if="site.url" :href="site.url" class="mt-6 block">
            <Button variant="solid" size="md" class="w-full">Go to your site</Button>
          </a>
        </div>

        <div v-else key="provisioning" class="mt-6">
          <div class="h-2 w-full overflow-hidden rounded-full bg-surface-gray-2">
            <div
              class="h-full rounded-full bg-surface-gray-10 transition-[width] duration-700 ease-out"
              :style="{ width: `${progress}%` }"
            />
          </div>

          <div class="mt-5 flex items-center gap-2 text-p-base text-ink-gray-7">
            <span class="lucide-info size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
            <Transition name="status-swap" mode="out-in">
              <span :key="phase">{{ statusLine }}</span>
            </Transition>
          </div>

          <Transition name="error-fade">
            <ErrorMessage v-if="error" class="mt-4" :message="error" />
          </Transition>
        </div>
      </Transition>
    </template>
  </MinimalAuthShell>
</template>

<style scoped>
.status-swap-enter-active {
  transition:
    opacity 200ms cubic-bezier(0.23, 1, 0.32, 1),
    transform 200ms cubic-bezier(0.23, 1, 0.32, 1);
}

.status-swap-leave-active {
  transition: opacity 150ms ease;
}

.status-swap-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.status-swap-leave-to {
  opacity: 0;
}
</style>
