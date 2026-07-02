
export interface PilotCredential{
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
	/**	Pilot Credential ID : Data - Central-minted identity of this pilot→Central credential. Atlas binds it to the pilot it deploys and echoes it back so Central can join events to the credential.	*/
	pilot_credential_id: string
	/**	Team : Link - Team - Owning Central team — the authorization context this credential carries.	*/
	team: string
	/**	Asset : Link - Asset - Soft reference to the hosting VM. Many benches may map to one Asset; not the identity key.	*/
	asset?: string
	/**	Token Hash : Data - Hash of the bearer token. The plaintext is returned once at mint and never stored.	*/
	token_hash?: string
	/**	Status : Select	*/
	status?: "Active" | "Revoked"
	/**	Expires At : Datetime - Optional hard expiry. Empty means no expiry.	*/
	expires_at?: string
	/**	Last Used At : Datetime - Stamped on each successful bench to Central call.	*/
	last_used_at?: string
}