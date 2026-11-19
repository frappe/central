export interface TeamService {
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
	/**	Team : Link - Team	*/
	team: string
	/**	Service : Select	*/
	add_on_service: 'storage' | 'ai'
	/**	Region : Link - Region	*/
	region?: string
	/**	Status : Select	*/
	status: 'Active' | 'Suspended'
	/**	Subscription : Link - Subscription - Set once the service is billed. A service being provisioned has none yet.	*/
	subscription?: string
	/**	Endpoint URL : Data - What the service is called at: the gateway a team's AI keys call, or a bucket's S3 endpoint.	*/
	endpoint_url?: string
	/**	Bucket Name : Data	*/
	bucket_name?: string
	/**	Access Key : Data	*/
	access_key?: string
	/**	Secret Access Key : Password	*/
	secret_access_key?: string
}
