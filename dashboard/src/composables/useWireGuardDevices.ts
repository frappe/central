import { call, frappeRequest } from 'frappe-ui'
import { ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type {
	WireGuardDevice,
	WireGuardRegion,
	WireGuardServer,
} from '@/types/wireguard'

interface DeviceList {
	devices: WireGuardDevice[]
	regions: WireGuardRegion[]
	servers: WireGuardServer[]
}

export function useWireGuardDevices() {
	const { activeTeam } = useSession()
	const devices = ref<WireGuardDevice[]>([])
	const regions = ref<WireGuardRegion[]>([])
	const servers = ref<WireGuardServer[]>([])
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		error.value = ''
		if (!activeTeam.value) {
			loading.value = false
			return
		}
		loading.value = true
		try {
			const result = await frappeRequest<DeviceList>({
				url: methodV1(API.listWireGuardDevices),
				method: 'GET',
				params: { team: activeTeam.value },
			})
			if (current !== generation) return
			devices.value = result.devices
			regions.value = result.regions
			servers.value = result.servers
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(failure, "Devices couldn't be loaded.")
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch(
		activeTeam,
		() => {
			devices.value = []
			regions.value = []
			servers.value = []
			reload()
		},
		{ immediate: true },
	)

	async function create(
		region: string,
		title: string,
		publicKey: string,
	): Promise<WireGuardDevice> {
		const device = await call<WireGuardDevice>(API.createWireGuardDevice, {
			team: activeTeam.value,
			region,
			title,
			public_key: publicKey,
		})
		await reload()
		return device
	}

	async function remove(name: string): Promise<boolean> {
		const { is_removed } = await call<{ is_removed: boolean }>(
			API.deleteWireGuardDevice,
			{ team: activeTeam.value, name },
		)
		await reload()
		return is_removed
	}

	return { devices, regions, servers, loading, error, reload, create, remove }
}
