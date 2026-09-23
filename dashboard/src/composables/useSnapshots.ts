import { call, frappeRequest } from 'frappe-ui'
import { computed, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/toast'
import type {
	SnapshotList,
	SnapshotPricing,
	SnapshotServerSetting,
	VMSnapshotRow,
} from '@/types/snapshots'

export interface DeleteResult {
	deleted: string[]
	failed: Record<string, string>
}

// The team's snapshots, or one server's when `resourceId` is set. A late reply for a
// team or server the user already moved away from is dropped.
export function useSnapshots(resourceId?: Ref<string | null>) {
	const { activeTeam } = useSession()
	const data = ref<SnapshotList | null>(null)
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		error.value = ''
		const team = activeTeam.value
		if (!team || (resourceId && !resourceId.value)) {
			data.value = null
			return
		}

		loading.value = true
		try {
			const result = await frappeRequest<SnapshotList>({
				url: methodV1(API.listSnapshots),
				method: 'GET',
				params: {
					team,
					...(resourceId?.value ? { resource_id: resourceId.value } : {}),
				},
			})
			if (current === generation) data.value = result
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(failure, "Snapshots couldn't be loaded.")
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch([activeTeam, () => resourceId?.value], reload, { immediate: true })

	async function take(serverId: string, title = ''): Promise<void> {
		await call(API.takeSnapshot, {
			team: activeTeam.value,
			resource_id: serverId,
			title,
		})
		await reload()
	}

	async function keep(name: string): Promise<void> {
		await call(API.keepSnapshot, { team: activeTeam.value, name })
		await reload()
	}

	async function remove(names: string[]): Promise<DeleteResult> {
		const result = await call<DeleteResult>(API.deleteSnapshots, {
			team: activeTeam.value,
			names,
		})
		await reload()
		return result
	}

	async function setAutomatic(serverId: string, enabled: boolean) {
		const setting = await call<SnapshotServerSetting>(
			API.setAutomaticSnapshots,
			{
				team: activeTeam.value,
				resource_id: serverId,
				enabled: enabled ? 1 : 0,
			},
		)
		if (data.value) data.value = { ...data.value, server: setting }
	}

	return {
		snapshots: computed<VMSnapshotRow[]>(() => data.value?.snapshots ?? []),
		currency: computed(() => data.value?.currency ?? 'INR'),
		freePerServer: computed(() => data.value?.free_per_server ?? 2),
		dailyRetentionHours: computed(
			() => data.value?.daily_retention_hours ?? 48,
		),
		rates: computed(() => data.value?.rates ?? {}),
		server: computed(() => data.value?.server ?? null),
		loading,
		error,
		reload,
		take,
		keep,
		remove,
		setAutomatic,
	}
}

// The price per GB-month of a snapshot in one region, shown before the customer commits.
export function useSnapshotPricing(region: Ref<string | null>) {
	const { activeTeam } = useSession()
	const pricing = ref<SnapshotPricing | null>(null)
	let generation = 0

	async function reload() {
		const current = ++generation
		pricing.value = null
		if (!activeTeam.value || !region.value) return
		try {
			const result = await frappeRequest<SnapshotPricing>({
				url: methodV1(API.snapshotPricing),
				method: 'GET',
				params: { team: activeTeam.value, region: region.value },
			})
			if (current === generation) pricing.value = result
		} catch {
			// The price is advice beside the action; the action itself still reports failure.
		}
	}

	watch([activeTeam, region], reload, { immediate: true })
	return {
		rate: computed(() => pricing.value?.rate_per_gib ?? null),
		currency: computed(() => pricing.value?.currency ?? 'INR'),
		freePerServer: computed(() => pricing.value?.free_per_server ?? 2),
	}
}
