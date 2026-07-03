<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Avatar, Button } from 'frappe-ui'
import Skeleton from '../common/Skeleton.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ListViewState from '@/components/common/list-view/ListViewState.vue'
import { useMyInvitations } from '@/composables/useMyInvitations'
import { formatDate } from '@/lib/format'
import type { MyInvitation } from '@/types/api'

// The signed-in user's pending invitations across teams. Reached from the
// Invitations tab or an email link (/invitations/:name focuses one invite).
// Accepting joins the team and switches to it; declining clears the invite.
const route = useRoute()
const { invitations, loading, busy, accept, decline } = useMyInvitations()

const focusedName = computed(() => (route.params.name as string | undefined) ?? null)

const shown = computed<MyInvitation[]>(() =>
  focusedName.value ? invitations.value.filter((i) => i.name === focusedName.value) : invitations.value,
)

const focusedMissing = computed(
  () => !!focusedName.value && !loading.value && shown.value.length === 0,
)
</script>

<template>
  <div class="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
    <div v-if="loading" class="mx-auto max-w-2xl space-y-3">
      <Skeleton v-for="n in 2" :key="n" class="h-24 rounded-lg" />
    </div>

    <ListViewState
      v-else-if="focusedMissing"
      kind="empty"
      title="This invitation isn't available"
      description="It may have been accepted, declined, revoked, expired, or sent to a different account."
    />

    <EmptyState
      v-else-if="!shown.length"
      title="No invitations"
      description="Invitations sent to you will appear here."
    />

    <div v-else class="mx-auto max-w-2xl space-y-4">
      <article
        v-for="invite in shown"
        :key="invite.name"
        class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5"
      >
        <div class="flex items-start gap-3">
          <Avatar :label="invite.team_name" size="xl" />
          <div class="min-w-0 flex-1">
            <h2 class="truncate text-base font-semibold text-ink-gray-9">{{ invite.team_name }}</h2>
            <p class="mt-0.5 text-p-sm text-ink-gray-5">
              Invited as <span class="font-medium text-ink-gray-7">{{ invite.role }}</span>
              <template v-if="invite.invited_by"> by {{ invite.invited_by }}</template>
            </p>
            <p v-if="invite.expires_on" class="mt-1 text-xs text-ink-gray-5">
              Expires {{ formatDate(invite.expires_on) }}
            </p>
          </div>
        </div>
        <div class="mt-4 flex items-center gap-2">
          <Button variant="solid" label="Accept & join" :loading="busy === invite.name" @click="accept(invite)" />
          <Button label="Decline" :loading="busy === invite.name" @click="decline(invite)" />
        </div>
      </article>
    </div>
  </div>
</template>
