<script setup lang="ts">
import { ref } from 'vue'
import { Tabs } from 'frappe-ui'
import MembersPanel from '@/components/team/MembersPanel.vue'
import RolesPanel from '@/components/team/RolesPanel.vue'

// Members and roles are two views of the same thing — who is on the team and what
// each role grants — so they live on one page behind tabs rather than two routes.
// The tab bar is the page's header; no separate title band above it.
const tabIndex = ref(0)
const tabs = [
  { label: 'Members', icon: 'lucide-users' },
  { label: 'Roles', icon: 'lucide-shield-check' },
]
</script>

<template>
  <div class="flex h-full flex-col">
    <Tabs v-model="tabIndex" :tabs="tabs">
      <template #tab-panel="{ tab }">
        <MembersPanel v-if="tab.label === 'Members'" />
        <RolesPanel v-else />
      </template>
    </Tabs>
  </div>
</template>
