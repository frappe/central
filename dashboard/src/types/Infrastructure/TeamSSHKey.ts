export interface TeamSSHKey {
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
	/**	Name : Data - A name the team can recognize, such as Work laptop.	*/
	title: string
	/**	Team : Link - Team	*/
	team: string
	/**	Fingerprint : Data	*/
	fingerprint?: string
	/**	SSH Public Key : Long Text - Paste one complete OpenSSH public key. Never paste a private key.	*/
	public_key: string
	/**	Last Sync Error : Small Text - The last regional synchronization failure, if any.	*/
	last_sync_error?: string
}
