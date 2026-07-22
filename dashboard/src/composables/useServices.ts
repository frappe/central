import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { submitOrThrow } from '@/lib/frappeCall'
import { successToast, errorToast } from '@/lib/toast'

// The team's add-on services (LLM hosting via Grove today). One module-level
// composable so the catalogue and the detail page share one fetch of offers +
// sites, and so row-level `busy` is consistent across the sites table. Mutations
// follow the house shape: submitOrThrow → toast → reload, with errors surfaced as
// toasts. The server re-checks every capability; the UI just avoids offering a
// button the API would 403.

export interface ServiceOffer {
	name: string
	title: string
	plan_category: string
	managed_service: string | null
}

export interface ServiceModel {
	name: string
	tier: string
}

export interface ServiceInstance {
	managed_service: string
	service: string
	status: string
	plan: string | null
	plan_title: string | null
	enabled_sites: string[]
	models: ServiceModel[]
}

export interface TeamSite {
	name: string
	status: string
	url: string
}

export interface SiteCredential {
	site: string
	gateway_url: string
	api_key: string
	provider_ref: string | null
	status: string
}

// A team-level issued key, as listed (no secret).
export interface ServiceApiKey {
	name: string
	label: string
	status: string
	gateway_url: string | null
	last_usage_total: number
	creation: string
}

// The secret + endpoint, returned on generate and on reveal.
export interface RevealedKey {
	name: string
	label: string
	gateway_url: string
	api_key: string
}

const { activeTeam } = useSession()

const offersCall = useCall<ServiceOffer[], { team: string }>({
	url: method(API.listOffers),
	params: teamParams,
	immediate: false,
	refetch: true,
})

const sitesCall = useCall<TeamSite[], { team: string }>({
	url: method(API.serviceSites),
	params: teamParams,
	immediate: false,
	refetch: true,
})

whenTeamReady(() => {
	offersCall.reload()
	sitesCall.reload()
})

// The detail page views one managed service at a time, so a single instance call
// reloaded by a bound ref is enough (no per-instance fetch to juggle).
const managedRef = ref('')
const instanceCall = useCall<ServiceInstance, { managed_service: string }>({
	url: method(API.serviceInstance),
	params: () => ({ managed_service: managedRef.value }),
	immediate: false,
})

const activateCall = useCall<
	{ managed_service: string; status: string },
	{ team: string; service: string }
>({ url: method(API.activateService), method: 'POST', immediate: false })

const enableCall = useCall<
	{ credential: string; site: string; status: string },
	{ managed_service: string; site: string }
>({ url: method(API.enableServiceSite), method: 'POST', immediate: false })

const disableCall = useCall<
	{ site: string; status: string },
	{ managed_service: string; site: string }
>({ url: method(API.disableServiceSite), method: 'POST', immediate: false })

const credentialCall = useCall<
	SiteCredential,
	{ managed_service: string; site: string }
>({ url: method(API.serviceCredential), method: 'POST', immediate: false })

// API keys: a list bound to a managed service, plus the three mutations.
const apiKeysManagedRef = ref('')
const apiKeysCall = useCall<ServiceApiKey[], { managed_service: string }>({
	url: method(API.listApiKeys),
	params: () => ({ managed_service: apiKeysManagedRef.value }),
	immediate: false,
})

const generateKeyCall = useCall<
	RevealedKey & { status: string },
	{ managed_service: string; label: string }
>({ url: method(API.generateApiKey), method: 'POST', immediate: false })

const revealKeyCall = useCall<RevealedKey, { name: string }>({
	url: method(API.revealApiKey),
	method: 'POST',
	immediate: false,
})

const revokeKeyCall = useCall<
	{ name: string; status: string },
	{ name: string }
>({ url: method(API.revokeApiKey), method: 'POST', immediate: false })

// Row-level busy: the site name (or key) currently mutating, so its control alone spins.
const busySite = ref('')
const busyKey = ref('')

function reloadInstance(): Promise<unknown> | void {
	if (managedRef.value) return instanceCall.reload()
}

function reloadApiKeys(): Promise<unknown> | void {
	if (apiKeysManagedRef.value) return apiKeysCall.reload()
}

export function useServices() {
	return {
		offers: computed(() => offersCall.data ?? []),
		offersLoading: computed(() => offersCall.loading),
		offersError: computed(() => offersCall.error),
		reloadOffers: () => offersCall.reload(),

		sites: computed(() => sitesCall.data ?? []),
		sitesLoading: computed(() => sitesCall.loading),

		instance: computed<ServiceInstance | null>(() => instanceCall.data ?? null),
		instanceLoading: computed(() => instanceCall.loading),
		instanceError: computed(() => instanceCall.error),
		loadInstance(managedService: string): Promise<unknown> {
			managedRef.value = managedService
			return instanceCall.reload()
		},

		busySite: computed(() => busySite.value),

		// Activate returns the new managed-service name so the caller can render its
		// detail immediately. Errors bubble (the no-subscription case is a real,
		// actionable message) — the caller decides how to surface them.
		async activate(service: string): Promise<string> {
			const team = activeTeam.value!
			await submitOrThrow(activateCall, { team, service })
			await offersCall.reload()
			return activateCall.data!.managed_service
		},

		async enableSite(managedService: string, site: string): Promise<void> {
			busySite.value = site
			try {
				await submitOrThrow(enableCall, {
					managed_service: managedService,
					site,
				})
				successToast(`AI enabled for ${site}.`)
				await reloadInstance()
			} catch (e) {
				errorToast(e)
			} finally {
				busySite.value = ''
			}
		},

		async disableSite(managedService: string, site: string): Promise<void> {
			busySite.value = site
			try {
				await submitOrThrow(disableCall, {
					managed_service: managedService,
					site,
				})
				successToast(`AI disabled for ${site}.`)
				await reloadInstance()
			} catch (e) {
				errorToast(e)
			} finally {
				busySite.value = ''
			}
		},

		// Reveal is on-demand (opens the connection dialog); it throws so the dialog
		// can show its own inline error state rather than a toast.
		async fetchCredential(
			managedService: string,
			site: string,
		): Promise<SiteCredential> {
			await submitOrThrow(credentialCall, {
				managed_service: managedService,
				site,
			})
			return credentialCall.data!
		},

		// ── Team-level API keys ──
		apiKeys: computed(() => apiKeysCall.data ?? []),
		apiKeysLoading: computed(() => apiKeysCall.loading),
		busyKey: computed(() => busyKey.value),
		loadApiKeys(managedService: string): Promise<unknown> {
			apiKeysManagedRef.value = managedService
			return apiKeysCall.reload()
		},

		// Generate + reveal throw so the caller can show the secret (or an inline
		// error) itself; revoke follows the toast+reload row pattern.
		async generateApiKey(
			managedService: string,
			label: string,
		): Promise<RevealedKey> {
			await submitOrThrow(generateKeyCall, {
				managed_service: managedService,
				label,
			})
			await reloadApiKeys()
			return generateKeyCall.data!
		},

		async revealKey(name: string): Promise<RevealedKey> {
			await submitOrThrow(revealKeyCall, { name })
			return revealKeyCall.data!
		},

		async revokeKey(name: string): Promise<void> {
			busyKey.value = name
			try {
				await submitOrThrow(revokeKeyCall, { name })
				successToast('API key revoked.')
				await reloadApiKeys()
			} catch (e) {
				errorToast(e)
			} finally {
				busyKey.value = ''
			}
		},
	}
}
