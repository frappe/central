export interface Product {
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
	/**	Product Key : Data - The value in the signup link, such as raven in /signup?product=raven. It cannot change after creation.	*/
	product_key: string
	/**	Title : Data	*/
	title: string
	/**	Enabled : Check - A disabled product refuses new signups. Its existing sites keep running.	*/
	enabled?: 0 | 1
	/**	Logo : Attach Image	*/
	logo?: string
	/**	Subtitle : Small Text - Shown under the heading on the signup and login pages. Leave empty to show no subtitle.	*/
	subtitle?: string
	/**	Signup App : Data - The app Cargo installs on this product's image, such as raven. A trial starts the newest signup image whose app tag has this value.	*/
	signup_app: string
}
