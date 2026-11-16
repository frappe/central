import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerMapData } from '@/composables/useServerMapData'
import { useWireGuardDevices } from '@/composables/useWireGuardDevices'
import { toCidr } from '@/lib/firewall'

interface AddressNameScope {
	/** Only devices and servers in this region. All regions when left out. */
	region?: MaybeRefOrGetter<string | undefined>
	/** The server whose firewall is edited. It is not offered as its own source. */
	resourceId?: MaybeRefOrGetter<string | undefined>
}

/** Names for the addresses a firewall rule can name: the team's VPN devices and its other servers. */
export function useFirewallAddressNames(scope: AddressNameScope = {}) {
	const { canManageWireGuard } = useCapabilities()
	const { devices } = useWireGuardDevices(canManageWireGuard)
	const { servers } = useServerMapData()

	const isInRegion = (region: string): boolean => {
		const wanted = toValue(scope.region)
		return !wanted || region === wanted
	}

	const serverNames = computed(() =>
		servers.value
			.filter(
				(server) =>
					server.ipv6_address &&
					isInRegion(server.region) &&
					server.resource_id !== toValue(scope.resourceId),
			)
			.map((server) => [
				toCidr(server.ipv6_address!),
				server.title || server.resource_id,
			]),
	)

	const deviceNames = computed(() =>
		devices.value
			.filter((device) => isInRegion(device.region))
			.map((device) => [toCidr(device.address), device.title]),
	)

	return {
		names: computed<Record<string, string>>(() =>
			Object.fromEntries([...serverNames.value, ...deviceNames.value]),
		),
	}
}
