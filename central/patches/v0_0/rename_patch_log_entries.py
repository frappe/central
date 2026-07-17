"""Re-key Patch Log after the patch tree reshuffle.

Patches used to live one-per-directory with a serial vNN prefix
(central.billing.patches.v26_... on an app that never shipped v1).
They now live flat under central/patches/v0_0/, frappe-style, so every
dotted path in patches.txt changed. Patch Log stores the dotted path,
so without this rename every already-run patch would execute again.

Must stay the first pre_model_sync entry: run_all prefetches the
executed set, but run_single re-checks Patch Log per patch, so rows
renamed here are seen as executed for the rest of the same migrate.
"""

import frappe

RENAMED_PATCHES = [
	"central.billing.patches.v01_rates_to_standalone.snapshot_legacy_rate_children",
	"central.billing.patches.v01_rates_to_standalone.migrate_rate_children_to_standalone",
	"central.billing.patches.v02_payment_method_priority.backfill_priority",
	"central.billing.patches.v03_team_link_to_central_team.migrate_team_to_central_team",
	"central.billing.patches.v03_team_link_to_central_team.validate_team_links",
	"central.billing.patches.v04_drop_orphan_billing_roles.drop_billing_roles",
	"central.billing.patches.v05_billing_workspace.reload_billing_workspace",
	"central.billing.patches.v06_payment_gateway_currency.migrate_gateway_currencies",
	"central.billing.patches.v07_credit_wallet_balance.backfill_wallet_balance",
	"central.billing.patches.v08_titlecase_select_options.titlecase_options",
	"central.billing.patches.v09_billing_currency.billing_currency",
	"central.billing.patches.v10_gateway_customer.backfill_gateway_customers",
	"central.billing.patches.v11_provision_gateway_customers.provision_gateway_customers",
	"central.billing.patches.v12_trust_tier_currency_thresholds.trust_tier_thresholds",
	"central.billing.patches.v13_drop_trust_tier_doctype.drop_trust_tier",
	"central.billing.patches.v14_titlecase_collection_mode.titlecase_collection_mode",
	"central.billing.patches.v15_catalog_taxonomy_masters.catalog_taxonomy",
	"central.billing.patches.v16_product_families.product_families",
	"central.billing.patches.v17_configurator_taxonomy_alignment.configurator_taxonomy_alignment",
	"central.billing.patches.v18_drop_unused_category_billing_meta.drop_unused_category_billing_meta",
	"central.billing.patches.v19_sub_category_memory_ratio.sub_category_memory_ratio",
	"central.billing.patches.v20_configurator_vcpu_dropdown.configurator_vcpu_dropdown",
	"central.billing.patches.v21_category_provision_target.category_provision_target",
	"central.billing.patches.v22_retire_addon_into_plan.retire_addon_into_plan",
	"central.billing.patches.v23_sub_category_compose_bounds.sub_category_compose_bounds",
	"central.billing.patches.v24_widen_vcpu_ladder.widen_vcpu_ladder",
	"central.billing.patches.v25_retire_price_lock.retire_price_lock",
	"central.billing.patches.v26_cancel_terminated_subscriptions.cancel_terminated_subscriptions",
	"central.patches.v01_capability_model_v2.rename_capabilities",
	"central.patches.v02_portal_central_users.make_central_users_portal_only",
	"central.patches.v03_strip_to_server_caps.strip_capabilities",
	"central.patches.v04_region_from_atlas_instance.backfill_region",
]


def execute():
	for old_path in RENAMED_PATCHES:
		new_path = "central.patches.v0_0." + old_path.rsplit(".", 1)[1]
		if frappe.db.exists("Patch Log", {"patch": old_path}):
			frappe.db.set_value("Patch Log", {"patch": old_path}, "patch", new_path)
