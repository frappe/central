import frappe

from central.infrastructure.doctype.github_installation.github_installation import GitHubInstallation

OLD_DOCTYPE = "GitHub Deploy App Installation"


def execute() -> None:
	"""Give each team's GitHub App installation one GitHub Installation, and link its server grants and deploy
	apps to it. The old columns and table are read here, before the old DocType is removed."""
	move_deploy_installations()
	move_connection_installations()


def move_deploy_installations() -> None:
	if not frappe.db.table_exists(OLD_DOCTYPE):
		return

	old = frappe.qb.DocType(OLD_DOCTYPE)
	rows = (
		frappe.qb.from_(old)
		.select(old.name, old.team, old.installation_id, old.account, old.account_type, old.status)
		.run(as_dict=True)
	)
	for row in rows:
		installation = GitHubInstallation.link(row.team, row)
		if row.status == "Disabled":
			frappe.db.set_value("GitHub Installation", installation.name, "status", "Disabled")
		frappe.db.set_value("Deploy App", {"installation": row.name}, "installation", installation.name)

	frappe.delete_doc("DocType", OLD_DOCTYPE, force=True, ignore_missing=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{OLD_DOCTYPE}`")


def move_connection_installations() -> None:
	if not frappe.db.has_column("GitHub Connection", "installation_id"):
		return

	connection = frappe.qb.DocType("GitHub Connection")
	rows = (
		frappe.qb.from_(connection)
		.select(
			connection.name,
			connection.team,
			connection.installation_id,
			connection.account,
			connection.account_type,
		)
		.where(connection.installation.isnull() | (connection.installation == ""))
	).run(as_dict=True)
	for row in rows:
		installation = GitHubInstallation.link(row.team, row)
		frappe.db.set_value(
			"GitHub Connection", row.name, "installation", installation.name, update_modified=False
		)
