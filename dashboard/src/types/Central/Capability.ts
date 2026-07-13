
export interface Capability{
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
	/**	Capability : Data	*/
	capability: string
	/**	Plane : Select	*/
	plane: "central" | "atlas" | "bench"
	/**	Resource : Data	*/
	resource: string
	/**	Description : Small Text	*/
	description?: string
}