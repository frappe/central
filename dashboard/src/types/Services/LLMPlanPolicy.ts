import { LLMPlanTier } from './LLMPlanTier'

export interface LLMPlanPolicy {
	name: string
	creation: string
	modified: string
	owner: string
	modified_by: string
	docstatus: 0 | 1 | 2
	parent?: string
	parentfield?: string
	parenttype?: string
	idx?: number
	/**	Plan : Link - Plan	*/
	plan: string
	/**	Allowed Tiers : Table - LLM Plan Tier	*/
	allowed_tiers?: LLMPlanTier[]
}
