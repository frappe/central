import { frappeRequest, useCall } from 'frappe-ui'
import { computed, type Ref, ref, watch } from 'vue'
import { API, method, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import { money } from '@/lib/format'

export type IpVersion = 4 | 6

interface PublicIpv4Pricing {
	rate: number | null
	currency: string
}

/** The monthly price of one public IPv4 in a region, shown before the customer commits. */
export function usePublicIpv4Pricing(region: Ref<string | null | undefined>) {
	const { activeTeam } = useSession()
	const pricing = ref<PublicIpv4Pricing | null>(null)
	let generation = 0

	async function reload(): Promise<void> {
		const current = ++generation
		pricing.value = null
		if (!activeTeam.value || !region.value) return
		try {
			const result = await frappeRequest<PublicIpv4Pricing>({
				url: methodV1(API.publicIpv4Pricing),
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
		/** Null while loading, or when the region has no price. */
		priceLabel: computed(() =>
			pricing.value?.rate == null
				? null
				: `${money(pricing.value.rate, pricing.value.currency, { trimTrailingZeros: true })}/mo`,
		),
	}
}

/** Attaches or detaches a server's public addresses, and turns IPv4 internet access on or off. */
export function useServerAddresses(resourceId: Ref<string>) {
	const { activeTeam } = useSession()

	const addressCall = useCall<
		{ is_pending: boolean },
		{
			team: string
			resource_id: string
			version: IpVersion
			is_attached: boolean
		}
	>({ url: method(API.setServerPublicIp), method: 'POST', immediate: false })

	const internetCall = useCall<
		null,
		{ team: string; resource_id: string; enabled: boolean }
	>({
		url: method(API.setServerIpv4Internet),
		method: 'POST',
		immediate: false,
	})

	/** Returns the error, or null when Atlas took the change. */
	async function setPublicIp(
		version: IpVersion,
		isAttached: boolean,
	): Promise<{ error: string | null; isPending: boolean }> {
		if (!activeTeam.value) return { error: null, isPending: false }

		await addressCall.submit({
			team: activeTeam.value,
			resource_id: resourceId.value,
			version,
			is_attached: isAttached,
		})
		if (addressCall.error)
			return {
				error: getErrorMessage(
					addressCall.error,
					"The address wasn't changed.",
				),
				isPending: false,
			}

		return { error: null, isPending: !!addressCall.data?.is_pending }
	}

	/** Returns the error, or null when it changed. */
	async function setIpv4Internet(enabled: boolean): Promise<string | null> {
		if (!activeTeam.value) return null

		await internetCall.submit({
			team: activeTeam.value,
			resource_id: resourceId.value,
			enabled,
		})
		return internetCall.error
			? getErrorMessage(
					internetCall.error,
					"IPv4 internet access wasn't changed.",
				)
			: null
	}

	return {
		setPublicIp,
		setIpv4Internet,
		isSaving: computed(() => addressCall.loading || internetCall.loading),
	}
}
