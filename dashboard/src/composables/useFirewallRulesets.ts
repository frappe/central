import { call, frappeRequest } from 'frappe-ui'
import { ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { FirewallRules } from '@/lib/firewall'
import { __ } from '@/lib/translate'
import type { FirewallRuleset } from '@/types/firewallRulesets'

/** The team's firewall rulesets, and the changes a member can make to them. */
export function useFirewallRulesets() {
	const { activeTeam } = useSession()
	const rulesets = ref<FirewallRuleset[]>([])
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		error.value = ''
		if (!activeTeam.value) {
			rulesets.value = []
			loading.value = false
			return
		}
		loading.value = true
		try {
			const rows = await frappeRequest<FirewallRuleset[]>({
				url: methodV1(API.listFirewallRulesets),
				method: 'GET',
				params: { team: activeTeam.value },
			})
			if (current === generation) rulesets.value = rows
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					__("Firewall rulesets couldn't be loaded."),
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch(activeTeam, reload, { immediate: true })

	/** Create a ruleset, or change the one in `name`. */
	async function save(title: string, rules: FirewallRules, name?: string) {
		await call(API.saveFirewallRuleset, {
			team: activeTeam.value,
			title,
			rules,
			name,
		})
		await reload()
	}

	async function remove(name: string) {
		await call(API.deleteFirewallRuleset, { team: activeTeam.value, name })
		await reload()
	}

	/** Make a server use exactly these rulesets. With none, it keeps the rules as its own. */
	async function apply(resourceId: string, rulesets: string[]) {
		await call(API.setServerFirewallRulesets, {
			team: activeTeam.value,
			resource_id: resourceId,
			rulesets,
		})
		await reload()
	}

	return { rulesets, loading, error, reload, save, remove, apply }
}
