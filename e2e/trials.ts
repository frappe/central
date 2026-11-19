import { expect } from '@playwright/test'
import { test as base } from './fixtures'

const endpoint = (name) => `/api/method/central.tests.e2e_trials.${name}`

// Adds `trials`: a signed-in team with a seeded server, in a trial state or bought directly.
// Every seeded server is removed after the test, before the team itself.
export const test = base.extend({
	trials: async ({ request, users, teams }, use) => {
		const made = []

		const call = async (name, form) => {
			const res = await request.post(endpoint(name), { form })
			expect(res.ok(), `${name} failed: ${res.status()} ${await res.text()}`).toBeTruthy()
			return (await res.json()).message
		}

		const start = async ({ trialState = 'Active', currency = 'INR', status = 'Running' } = {}) => {
			const creds = await users.signIn({ scenario: 'ready', currency })
			await teams.setTrustTier({ team: creds.team })
			made.push(creds.team)
			const server = await call('seed_server', { team: creds.team, trial_state: trialState, days_left: 5, status })
			return { team: creds.team, ...server }
		}

		const addPaymentMethod = (team) => call('add_payment_method', { team })
		const queuePlanChange = ({ team, server, site }, status = 'In Progress') =>
			call('queue_plan_change', { team, server, site, status })
		const setActionStatus = (action, status) => call('set_action_status', { action, status })

		await use({ start, addPaymentMethod, queuePlanChange, setActionStatus })

		for (const team of made) await call('teardown_servers', { team }).catch(() => {})
	},
})

export { expect }
