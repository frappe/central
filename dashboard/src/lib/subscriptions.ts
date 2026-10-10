import type { SubscriptionRow } from '@/types/billing'

/** What a customer calls the subscription: its server's display name, else its plan, else the server ID. */
export function subscriptionTitle(sub: SubscriptionRow): string {
	return sub.server || sub.plan_title || sub.resource_id || sub.name
}
