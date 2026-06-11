<script setup>
import { ref, computed, watch } from 'vue'
import { useCall } from 'frappe-ui'
import { Dialog, Button, TextInput, LoadingText } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'

// Press-style team switcher. Members switch among the teams they belong to; a
// System Manager (operator) can additionally impersonate ANY team via search.
const open = defineModel({ type: Boolean, default: false })
const { currentTeam, setTeam, who, homeTeam, isOperator } = useTeam()

const myTeams = useCall({ url: m(API.myTeams) })

const search = ref('')
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  const list = myTeams.data || []
  if (!q) return list
  return list.filter(
    (t) => t.label.toLowerCase().includes(q) || (t.owner || '').toLowerCase().includes(q),
  )
})

// Operator-only impersonation: search every team server-side (debounced).
const opQuery = ref('')
const opResults = useCall({
  url: m(API.searchTeams),
  params: () => ({ query: opQuery.value, limit: 20 }),
  immediate: false,
})
let timer
watch(opQuery, () => {
  if (!isOperator.value) return
  clearTimeout(timer)
  timer = setTimeout(() => opResults.reload(), 250)
})
watch(open, (v) => {
  if (v && isOperator.value) opResults.reload()
})

const viewingLabel = computed(() => {
  const t = (myTeams.data || []).find((x) => x.name === currentTeam.value)
  return t?.label || currentTeam.value
})

function choose(name) {
  setTeam(name)
  open.value = false
}
function resetToHome() {
  setTeam(null)
  open.value = false
}
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Switch Team', size: 'lg' }">
    <template #body-content>
      <!-- Context -->
      <div class="mb-4 rounded bg-surface-gray-2 px-4 py-3 text-sm">
        <p class="text-ink-gray-7">
          Signed in as <span class="font-medium text-ink-gray-9">{{ who.data?.user }}</span>
        </p>
        <p class="text-ink-gray-7">
          Viewing dashboard for the team
          <span class="font-medium text-ink-gray-9">{{ viewingLabel }}</span>
        </p>
      </div>

      <TextInput v-model="search" type="text" placeholder="Search" class="mb-3">
        <template #prefix><span class="lucide-search size-4 text-ink-gray-5" /></template>
      </TextInput>

      <!-- Member teams -->
      <div v-if="myTeams.loading && !myTeams.data" class="space-y-2">
        <LoadingText :lines="3" />
      </div>
      <ul v-else class="divide-y divide-outline-gray-1">
        <li
          v-for="t in filtered"
          :key="t.name"
          class="flex items-center justify-between gap-3 py-3"
        >
          <div class="flex min-w-0 items-center gap-2">
            <span class="truncate text-sm text-ink-gray-8">{{ t.label }}</span>
            <span
              v-if="t.name === homeTeam"
              class="rounded-full bg-surface-blue-2 px-2 py-0.5 text-p-sm text-ink-blue-3"
            >
              Your team
            </span>
          </div>
          <Button
            :label="t.name === currentTeam ? 'Current' : 'Switch'"
            :disabled="t.name === currentTeam"
            @click="choose(t.name)"
          />
        </li>
        <li v-if="!filtered.length" class="py-6 text-center text-p-sm text-ink-gray-5">
          No teams match.
        </li>
      </ul>

      <!-- Operator impersonation -->
      <div v-if="isOperator" class="mt-5 border-t border-outline-gray-1 pt-4">
        <p class="mb-2 text-p-sm font-medium text-ink-gray-6">Impersonate any team</p>
        <TextInput v-model="opQuery" type="text" placeholder="Search all teams…">
          <template #prefix><span class="lucide-search size-4 text-ink-gray-5" /></template>
        </TextInput>
        <ul class="mt-2 max-h-52 divide-y divide-outline-gray-1 overflow-y-auto">
          <li
            v-for="t in (opResults.data || [])"
            :key="t.name"
            class="flex items-center justify-between gap-3 py-2.5"
          >
            <div class="min-w-0">
              <p class="truncate text-sm text-ink-gray-8">{{ t.label }}</p>
              <p v-if="t.owner && t.owner !== t.label" class="truncate text-p-sm text-ink-gray-5">
                {{ t.owner }}
              </p>
            </div>
            <Button
              :label="t.name === currentTeam ? 'Current' : 'Switch'"
              :disabled="t.name === currentTeam"
              @click="choose(t.name)"
            />
          </li>
          <li
            v-if="opQuery && !opResults.loading && !(opResults.data || []).length"
            class="py-4 text-center text-p-sm text-ink-gray-5"
          >
            No teams found.
          </li>
        </ul>
        <p class="mt-2 text-p-sm text-ink-gray-5">
          Impersonation is only available to system users.
        </p>
      </div>
    </template>

    <template #actions>
      <Button
        v-if="currentTeam !== homeTeam"
        variant="subtle"
        label="Back to my team"
        @click="resetToHome"
      />
    </template>
  </Dialog>
</template>
