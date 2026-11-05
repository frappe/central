import type { ProductEmailNote } from './ProductEmailNote'

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
	/**	Setup Messages : Small Text - Shown one at a time while a new site starts, one line per message. For example: Setting up channels. Leave empty to show general messages.	*/
	setup_messages?: string
	/**	Signup App : Data - The app Cargo installs on this product's image, such as raven. A trial starts the newest signup image whose app tag has this value.	*/
	signup_app: string
	/**	Frappe Version : Data - The Frappe branch of this product's trial image, such as develop or version-16. Cargo builds images only for the branches in Cargo Settings, so check with Preview Trial Images before you change it.	*/
	frappe_version: string
	/**	Landing Route : Data - Where the owner lands after signing in to a trial site, such as /raven, so the app can run its own setup. Leave empty to open Desk.	*/
	landing_route?: string
	/**	Trial Days : Int - Days a trial site of this product runs from when it is first ready. 0 uses Central Settings.	*/
	trial_days?: number
	/**	Trial Deletion Days : Int - Days a stopped trial site is kept before its server is terminated. 0 uses Central Settings.	*/
	trial_deletion_days?: number
	/**	Use Product Branding in Emails : Check - Show this product's logo and title instead of Frappe Cloud's in signup codes and in emails about its sites. Needs a public logo.	*/
	use_own_email_branding?: 0 | 1
	/**	Getting Started URL : Data - An https:// page that shows a new customer how to start, such as the product's docs. The site_ready and trial_unopened emails link to it with a Get started button.	*/
	getting_started_url?: string
	/**	Email Notes : Table - Product Email Note - An extra paragraph for a lifecycle email about a site of this product, such as what to do first in site_ready.	*/
	email_notes?: ProductEmailNote[]
}
