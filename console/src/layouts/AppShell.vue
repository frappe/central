<script setup lang="ts">
import { computed } from 'vue'
import { Sidebar, ToastProvider } from 'frappe-ui'
import { useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'
import { useSession } from '@/composables/useSession'
import { useCapabilities } from '@/composables/useCapabilities'

// App shell: the new frappe-ui Sidebar (collapsible, Espresso design system) +
// the routed page. The header doubles as the team switcher — switching re-drives
// the team-scoped reads (capabilities, registry). Sections are capability-gated.
const { teams, activeTeam, activeTeamLabel, setActiveTeam } = useSession()
const { canViewServers } = useCapabilities()
const { logout } = useAuth()
const { currentTheme, toggleTheme } = useTheme()

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
    items: [
      {
        label: 'Servers',
        icon: 'lucide-server',
        to: '/servers',
        condition: () => canViewServers.value,
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
  </div>
</template>
