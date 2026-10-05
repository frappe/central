import { TeamMember } from './TeamMember'
import { TeamOnboardingStep } from './TeamOnboardingStep'

export interface Team {
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
	/**	Naming Series : Select	*/
	naming_series: 'TEAM-.#####'
	/**	Team Name : Data	*/
	team_name: string
	/**	Team Logo : Attach Image	*/
	team_logo?: string
	/**	Owner User : Link - User	*/
	owner_user: string
	/**	Tenant ID : Int - Permanent numeric network identity shared by this Team. Assigned by Central.	*/
	tenant_id?: number
	/**	Status : Select	*/
	status: 'Active' | 'Suspended'
	/**	Staging Trial : Check - Staging trials: create servers on free welcome credits without a full billing profile. Central sets it from Billing Settings when the team is created. Only a System Manager can change it.	*/
	is_staging_trial?: 0 | 1
	/**	Members : Table - Team Member	*/
	members?: TeamMember[]
	/**	Onboarding Steps : Table - Team Onboarding Step - The console onboarding steps of this team, and what the owner did with each. Set when the team is created.	*/
	onboarding_steps?: TeamOnboardingStep[]
	/**	UTM Source : Data	*/
	utm_source?: string
	/**	UTM Medium : Data	*/
	utm_medium?: string
	/**	UTM Campaign : Data	*/
	utm_campaign?: string
	/**	Landing Product : Link - Product - The product whose signup link the owner first used.	*/
	landing_product?: string
	/**	Referrer : Small Text - The page that linked to the first signup page.	*/
	referrer?: string
}
