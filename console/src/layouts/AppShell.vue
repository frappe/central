<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Sidebar, ToastProvider } from 'frappe-ui'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import { useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'
import { useSession } from '@/composables/useSession'
import { useCapabilities } from '@/composables/useCapabilities'

// App shell: the new frappe-ui Sidebar (collapsible, Espresso design system) +
// the routed page. The header doubles as the team switcher — switching re-drives
// the team-scoped reads (capabilities, registry). Sections are capability-gated.
const { teams, activeTeam, activeTeamLabel, setActiveTeam } = useSession()
const { canViewServers, canViewBilling, isMember } = useCapabilities()
const { logout } = useAuth()
const { currentTheme, toggleTheme } = useTheme()
const createTeamOpen = ref(false)

// The map pages want the full viewport, so the sidebar defaults collapsed
// there and expanded everywhere else. Only crossing that boundary re-applies
// the default — toggling by hand sticks while you stay within a section.
const route = useRoute()
const inServersSection = (path: string) => path.startsWith('/servers')
const sidebarCollapsed = ref(inServersSection(route.path))
watch(
  () => route.path,
  (path, previous) => {
    if (inServersSection(path) !== inServersSection(previous)) {
      sidebarCollapsed.value = inServersSection(path)
    }
  },
)

// The collapse chevron follows the cursor down the sidebar's edge strip.
// Coalesce mousemove to one update per frame — the ref only drives a CSS offset,
// so more than one write per paint is wasted work.
const edgeY = ref(60)
let pendingEdgeY = 60
let edgeRaf = 0
function onEdgeMove(event: MouseEvent): void {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  pendingEdgeY = event.clientY - rect.top
  if (edgeRaf) return
  edgeRaf = requestAnimationFrame(() => {
    edgeY.value = pendingEdgeY
    edgeRaf = 0
  })
}

async function logoutAndRedirect() {
  await logout()
  window.location.replace('/dashboard/login')
}

// SidebarHeader renders `menuItems` as a dropdown (title + subtitle + chevron) —
// the team switcher. The active team carries a check; the rest switch on click.
const header = computed(() => ({
  title: 'Central Console',
  subtitle: activeTeamLabel.value,
  menuItems: [
    ...teams.value.map((team) => ({
      label: team.label,
      icon: team.name === activeTeam.value ? 'lucide-check' : 'lucide-users',
      onClick: () => setActiveTeam(team.name),
    })),
    {
      label: 'Create team',
      icon: 'lucide-plus',
      onClick: () => {
        createTeamOpen.value = true
      },
    },
    {
      label: 'Toggle Theme',
      icon: currentTheme.value === 'dark' ? 'lucide-sun' : 'lucide-moon',
      onClick: toggleTheme,
    },
    {
      label: 'Log out',
      icon: 'lucide-log-out',
      onClick: logoutAndRedirect,
    },
  ],
}))

const sections = computed(() => [
  {
    label: 'Compute',
    collapsible: true,
    items: [
      {
        label: 'Servers',
        icon: 'lucide-server',
        to: '/servers',
        condition: () => canViewServers.value,
      },
    ],
  },
  {
    label: 'Billing',
    collapsible: true,
    items: [
      {
        label: 'Overview',
        icon: 'lucide-credit-card',
        to: '/billing',
        condition: () => canViewBilling.value,
      },
      {
        label: 'Invoices',
        icon: 'lucide-file-text',
        to: '/billing/invoices',
        condition: () => canViewBilling.value,
      },
      {
        label: 'Limit Tiers',
        icon: 'lucide-gauge',
        to: '/billing/limits',
        condition: () => canViewBilling.value,
      },
    ],
  },
  {
    label: 'Team',
    collapsible: true,
    items: [
      {
        label: 'Members & roles',
        icon: 'lucide-users',
        to: '/team/members',
        condition: () => isMember.value,
      },
      {
        label: 'Invitations',
        icon: 'lucide-mail',
        to: '/team/invitations',
        condition: () => isMember.value,
      },
      {
        label: 'Settings',
        icon: 'lucide-settings',
        to: '/team/settings',
        condition: () => isMember.value,
      },
    ],
  },
])
</script>

<template>
  <!-- `isolate`: a stacking context here contains the sidebar's z-10 (below), so it
       can't leak to the body level and paint over body-teleported popovers — the team
       switcher dropdown was rendering behind the sidebar without this. -->
  <div class="isolate flex h-screen overflow-hidden bg-surface-base text-ink-gray-9">
    <!-- Collapse control: the whole right edge is the trigger; the chevron
         rides the cursor. The built-in bottom item is hidden below. z-10 lifts
         the sidebar's whole stacking context above the main pane — pages that
         isolate themselves (the map) otherwise paint over the knob's overhang,
         since later DOM order wins at equal z. -->
    <div class="sb-wrap relative isolate z-10 shrink-0">
      <Sidebar v-model:collapsed="sidebarCollapsed" :header="header" :sections="sections" class="h-full" />
      <button
        class="sb-edge absolute inset-y-0 -right-2 z-30 w-4 cursor-pointer"
        :aria-label="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @mousemove="onEdgeMove"
        @focus="edgeY = 60"
        @click="sidebarCollapsed = !sidebarCollapsed"
      >
        <span
          class="sb-edge-knob pointer-events-none absolute left-1/2 top-0 grid size-6 place-items-center rounded-full border border-outline-gray-2 bg-surface-elevation-1 text-ink-gray-6 shadow-sm"
          :style="{ transform: `translate(-50%, calc(${edgeY}px - 50%))` }"
        >
          <span class="size-3.5" :class="sidebarCollapsed ? 'lucide-chevron-right' : 'lucide-chevron-left'" />
        </span>
      </button>
    </div>
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <router-view />
    </main>
    <ToastProvider />
    <CreateTeamDialog v-model:open="createTeamOpen" />
  </div>
</template>

<style scoped>
/* frappe-ui Sidebar's built-in bottom Collapse/Expand item — replaced by the
   edge strip above. (Selector tracks Sidebar.vue's footer container.) */
.sb-wrap :deep(.mt-auto > button:last-child) {
  display: none;
}

/* The chevron knob is hidden until the edge is hovered or keyboard-focused;
   only opacity fades — its vertical position tracks the cursor instantly. */
.sb-edge-knob {
  opacity: 0;
  transition: opacity 150ms ease-out;
}
.sb-edge:hover .sb-edge-knob,
.sb-edge:focus-visible .sb-edge-knob {
  opacity: 1;
}
</style>
