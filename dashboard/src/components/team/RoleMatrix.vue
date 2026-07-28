<script setup lang="ts">
import { computed } from "vue";
import { Badge } from "frappe-ui";
import RoleRowActions from "@/components/team/RoleRowActions.vue";
import { groupCapabilitiesByPlane } from "@/lib/capabilities";
import type { CapabilityInfo, TeamRoleRow } from "@/types/api";

// Capability × role matrix: capabilities down the side (grouped by plane, each with
// its plain-English meaning), roles across the top, a check where the role grants
// the capability. One glance answers "who can do what" and lets roles be compared
// side by side — far clearer than reading one role at a time. The capability column
// is sticky horizontally and the role header sticky vertically so both stay in view.
const props = defineProps<{
	roles: TeamRoleRow[];
	capabilities: CapabilityInfo[];
	canManage: boolean;
	deletingName?: string;
}>();

const emit = defineEmits<{ delete: [role: TeamRoleRow] }>();

const groups = computed(() => groupCapabilitiesByPlane(props.capabilities));

// role name -> set of granted capabilities, for O(1) cell lookups.
const grantedByRole = computed<Record<string, Set<string>>>(() =>
	Object.fromEntries(props.roles.map((role) => [role.name, new Set(role.capabilities)]))
);

function grants(role: TeamRoleRow, capability: string): boolean {
	return grantedByRole.value[role.name]?.has(capability) ?? false;
}
</script>

<template>
	<!-- `isolate` keeps the sticky cells' z-index in their own stacking context so
       they don't paint over teleported overlays (dialogs/slide-overs) that sit at
       z-auto. -->
	<div class="isolate overflow-x-auto rounded-lg border border-outline-gray-2">
		<table class="w-full border-collapse text-left">
			<thead>
				<tr class="bg-surface-elevation-1">
					<th
						class="sticky left-0 z-20 min-w-[16rem] border-b border-outline-gray-2 bg-surface-elevation-1 px-4 py-3 text-xs font-medium uppercase tracking-wide text-ink-gray-5"
					>
						Capability
					</th>
					<th
						v-for="role in roles"
						:key="role.name"
						class="min-w-[7.5rem] border-b border-l border-outline-gray-1 px-3 py-3 align-top"
					>
						<div class="flex items-start justify-between gap-1">
							<div class="min-w-0">
								<p class="truncate text-sm font-semibold text-ink-gray-9">
									{{ role.role_name }}
								</p>
								<Badge
									v-if="!role.is_system"
									class="mt-1"
									theme="violet"
									label="Custom"
								/>
							</div>
							<RoleRowActions
								:role="role"
								:can-manage="canManage"
								:busy="deletingName === role.name"
								@delete="emit('delete', $event)"
							/>
						</div>
					</th>
				</tr>
			</thead>

			<tbody>
				<template v-for="group in groups" :key="group.plane">
					<tr>
						<td
							:colspan="roles.length + 1"
							class="sticky left-0 bg-surface-gray-2 px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-ink-gray-5"
						>
							{{ group.label }}
						</td>
					</tr>
					<tr
						v-for="cap in group.caps"
						:key="cap.name"
						class="border-b border-outline-gray-1 last:border-0"
					>
						<td class="sticky left-0 z-10 bg-surface-elevation-1 px-4 py-2.5">
							<p class="text-sm text-ink-gray-8">{{ cap.description }}</p>
							<p class="mt-0.5 font-mono text-xs text-ink-gray-4">
								{{ cap.name }}
							</p>
						</td>
						<td
							v-for="role in roles"
							:key="role.name"
							class="border-l border-outline-gray-1 px-3 py-2.5 text-center"
						>
							<svg
								v-if="grants(role, cap.name)"
								class="mx-auto h-4 w-4 text-ink-green-6"
								viewBox="0 0 16 16"
								fill="none"
								aria-label="granted"
							>
								<path
									d="M3.5 8.5l3 3 6-7"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
								/>
							</svg>
							<span v-else class="text-ink-gray-4" aria-label="not granted">–</span>
						</td>
					</tr>
				</template>
			</tbody>
		</table>
	</div>
</template>
