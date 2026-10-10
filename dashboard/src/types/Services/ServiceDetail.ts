export interface ServiceDetail {
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
	/**	Region : Link - Region - The region that runs this service and reports on it.	*/
	region: string
	/**	Service : Select	*/
	service: 'telemetry' | 'storage'
	/**	Status : Select - Reported by the region. Central never sets it by hand.	*/
	status: 'Available' | 'Not Available'
	/**	Activated On : Datetime - When the region last reported this service available.	*/
	activated_on?: string
	/**	Last Updated On : Datetime	*/
	last_updated_on?: string
	/**	Service Endpoint : Data - The URL consumers reach this service at, as the region reported it.	*/
	service_endpoint?: string
}
