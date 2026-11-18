import { ImageOfferingTag } from './ImageOfferingTag'

export interface ImageOffering {
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
	/**	Offering Key : Data - Stable product identifier, such as pilot-server.	*/
	offering_key: string
	/**	Display Name : Data	*/
	title: string
	/**	Enabled : Check	*/
	enabled?: 0 | 1
	/**	Available In : Select	*/
	available_in: 'Server' | 'Signup' | 'Both'
	/**	Display Order : Int - Offerings show in ascending order. Equal values sort by display name.	*/
	display_order?: number
	/**	Logo : Attach Image	*/
	logo?: string
	/**	Description : Small Text	*/
	description?: string
	/**	Plan Category : Link - Plan Category - The plan family a server from this offering is sold on. Leave blank to offer every server plan.	*/
	plan_category?: string
	/**	Minimum Memory (MiB) : Int - The smallest memory a server from this offering runs on. Smaller plans and custom sizes are not offered. Leave at 0 for no minimum.	*/
	minimum_memory_mib?: number
	/**	Required Image Tags : Table - Image Offering Tag - Every tag must match. Central only offers available, enabled System images.	*/
	required_tags: ImageOfferingTag[]
}
