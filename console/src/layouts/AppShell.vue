<script setup lang="ts">
import { computed, ref } from 'vue'
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
        label: 'Notifications',
        icon: 'lucide-bell',
        to: '/notifications',
        condition: () => isMember.value,
      },
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
  <div class="flex h-screen overflow-hidden bg-surface-base text-ink-gray-9">
    <Sidebar :header="header" :sections="sections" />
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <router-view />
    </main>
    <ToastProvider />
    <CreateTeamDialog v-model:open="createTeamOpen" />
  </div>
</template>
