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
	/**	Logo : Attach Image	*/
	logo?: string
	/**	Description : Small Text	*/
	description?: string
	/**	Required Image Tags : Table - Image Offering Tag - Every tag must match. Central only offers available, enabled System images.	*/
	required_tags: ImageOfferingTag[]
}
