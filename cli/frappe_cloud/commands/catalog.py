import argparse
from datetime import UTC, datetime

from frappe_cloud.commands import add_command, add_group
from frappe_cloud.commands.server import get_image_params, get_images
from frappe_cloud.context import Context


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "region", "See where servers can run.")
	add_command(commands, "list", list_regions, "List the regions that accept new servers.")

	commands = add_group(subparsers, "offering", "See the kinds of image a server can start from.")
	add_command(commands, "list", list_offerings, "List the image offerings.")

	commands = add_group(subparsers, "image", "See the images of an offering.")
	parser = add_command(commands, "list", list_images, "List an offering's images in a region.")
	parser.add_argument("--region", required=True, help="Region, from `fcloud region list`.")
	parser.add_argument("--offering", required=True, help="Offering, from `fcloud offering list`.")

	commands = add_group(subparsers, "plan", "See server plans and prices.")
	parser = add_command(commands, "list", list_plans, "List the plans a new server can use.")
	parser.add_argument("--region", required=True, help="Region, from `fcloud region list`.")
	parser.add_argument("--offering", help="Show only plans that fit this offering's newest image.")
	parser.add_argument("--image", help="Show only plans that fit this image of the offering.")
	parser.add_argument("--snapshot", help="Show only plans that fit this snapshot.")


def list_regions(context: Context, args: argparse.Namespace) -> None:
	regions = context.client.get("central.api.servers.list_instances", team=context.client.require_team())
	columns = [
		("Region", "region"),
		("Name", "display_name"),
		("Provider", "provider"),
		("Country", "country_code"),
		("Reachable", "reachable"),
	]
	context.output.table(regions, columns, empty="No region accepts new servers now.")


def list_offerings(context: Context, args: argparse.Namespace) -> None:
	offerings = context.client.get("central.api.images.list_offerings", team=context.client.require_team())
	context.output.table(
		offerings, [("Offering", "name"), ("Title", "title"), ("Description", "description")]
	)


def list_images(context: Context, args: argparse.Namespace) -> None:
	images = get_images(context, args.region, args.offering)
	columns = [
		("ID", "id"),
		("Title", "title"),
		("Architecture", "architecture"),
		("Size MiB", "rootfs_size_mib"),
		("Built", lambda image: datetime.fromtimestamp(image["created_at"], UTC).strftime("%Y-%m-%d %H:%M")),
	]
	context.output.table(images, columns, empty="This offering has no image in the region.")


def list_plans(context: Context, args: argparse.Namespace) -> None:
	team = context.client.require_team()
	if args.offering or args.image or args.snapshot:
		params = {"team": team, "region": args.region, **get_image_params(context, args)}
		catalog = context.client.get("central.api.images.eligible_plans", **params)
	else:
		catalog = context.client.get(
			"central.billing.api.dashboard.catalog.get_eligible_plans", team=team, cluster=args.region
		)

	plans = [plan for group in catalog["plans"].values() for plan in group]
	columns = [
		("Plan", "plan"),
		("Title", "title"),
		("Category", "sub_category"),
		("Includes", lambda plan: [format_include(include) for include in plan["includes"]]),
		("Rate", lambda plan: f"{plan['rate']:g} {plan['currency']}"),
		("Cycle", "billing_cycle"),
	]
	context.output.table(plans, columns, empty="No plan is available in this region.")


def format_include(include: dict) -> str:
	return " ".join(
		str(part)
		for part in (f"{include['quantity']:g}", include.get("unit"), include["resource_type"])
		if part
	)
