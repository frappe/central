export interface PilotCredential {
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
	/**	Pilot Credential ID : Data - Central-minted identity of this pilot→Central credential; Atlas echoes it back on events.	*/
	pilot_credential_id: string
	/**	Team : Link - Team - Owning Central team — the authorization context this credential carries.	*/
	team: string
	/**	Server : Link - Virtual Machine - Soft reference to the hosting VM. Many benches may map to one Virtual Machine; not the identity key. Bound later, once Atlas echoes the VM event.	*/
	server?: string
	/**	Audience ID : Data - The bench's audience id (its VM resource_id), stamped into the `aud` of every token Central mints for it. Set at enrollment; independent of the Virtual Machine link so it survives mirror lag.	*/
	audience_id?: string
	/**	Token Hash : Data - Hash of the bearer token. The plaintext is returned once at mint and never stored.	*/
	token_hash?: string
	/**	Status : Select	*/
	status?: 'Active' | 'Revoked'
	/**	Expires At : Datetime - Optional hard expiry. Empty means no expiry.	*/
	expires_at?: string
	/**	Last Used At : Datetime - Stamped on each successful bench to Central call.	*/
	last_used_at?: string
}
