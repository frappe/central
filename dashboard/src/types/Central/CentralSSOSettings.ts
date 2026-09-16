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
	/**	Central Public URL : Data - Public Central URL used as the RSA token issuer and to build the Pilot public-key URL. Leave blank to use the site URL. Atlas tokens use the fixed issuer central.	*/
	issuer_url?: string
	/**	RSA Key ID : Data - Identifies the RSA key used for Pilot and service tokens. Published with the public key.	*/
	kid?: string
	/**	RSA Public Key (PEM) : Code - PEM public key benches verify Central-minted tokens against. Published (as a JWK) at the JWKS endpoint.	*/
	public_key?: string
	/**	RSA Private Key (PEM) : Password - PEM private key Central signs with. Encrypted at rest; never leaves Central.	*/
	private_key?: string
	/**	Atlas Key ID : Data - Public key identifier in the central: namespace.	*/
	atlas_key_id?: string
	/**	Atlas Public Key (Ed25519 PEM) : Code - Public Ed25519 verification key published for Atlas.	*/
	atlas_public_key?: string
	/**	Atlas Private Key (Ed25519 PEM) : Password - Encrypted signing key. Never sent to Atlas.	*/
	atlas_private_key?: string
}
