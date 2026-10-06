export interface CentralSSOSettings {
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
	/**	Central Public URL : Data - Public Central URL used as the Pilot token issuer and to build the Pilot public-key URL. Leave blank to use the site URL. Atlas tokens use the fixed issuer central.	*/
	issuer_url?: string
	/**	Atlas Key ID : Data - Public key identifier in the central: namespace.	*/
	atlas_key_id?: string
	/**	Atlas Public Key (Ed25519 PEM) : Code - Public Ed25519 verification key published for Atlas.	*/
	atlas_public_key?: string
	/**	Atlas Private Key (Ed25519 PEM) : Password - Encrypted signing key. Never sent to Atlas.	*/
	atlas_private_key?: string
	/**	Pilot Key ID : Data - Public key identifier in the central: namespace.	*/
	pilot_key_id?: string
	/**	Pilot Public Key (Ed25519 PEM) : Code - Public Ed25519 verification key published for Pilot.	*/
	pilot_public_key?: string
	/**	Pilot Private Key (Ed25519 PEM) : Password - Encrypted signing key. Never sent to Pilot.	*/
	pilot_private_key?: string
}
