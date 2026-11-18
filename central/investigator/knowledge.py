from __future__ import annotations

from pathlib import Path

import frappe
import requests
from frappe.flow.knowledge import Knowledge

CENTRAL_KNOWLEDGE_BASE = "Central"
PILOT_KNOWLEDGE_BASE = "Pilot"
CENTRAL_PATTERNS = ("README.md", "CAPABILITIES.md", "spec/**/*.md", "docs/**/*.md", "central/**/*.md")
SKIPPED_FOLDERS = {"node_modules", ".git", "dist", ".tmp"}
PILOT_REPOSITORY = "frappe/pilot"
PILOT_REFERENCE = "develop"
GITHUB_TIMEOUT_SECONDS = 30


def get_knowledge_bases() -> list[Knowledge]:
	return [
		Knowledge(CENTRAL_KNOWLEDGE_BASE, description="Central handbook, specifications, and module notes."),
		Knowledge(
			PILOT_KNOWLEDGE_BASE, description="Pilot handbook: benches, sites, tasks, and the Admin API."
		),
	]


def load_knowledge_bases() -> dict[str, dict[str, int]]:
	"""Load the Central documents and the Pilot documents into their knowledge bases.

	A source keeps its repository path as its title. New files are added, changed files reloaded, and sources
	of removed files deleted. Run it after a deploy that changes the documents.
	"""
	return {
		CENTRAL_KNOWLEDGE_BASE: _sync(CENTRAL_KNOWLEDGE_BASE, get_central_documents()),
		PILOT_KNOWLEDGE_BASE: _sync(PILOT_KNOWLEDGE_BASE, get_pilot_documents()),
	}


def load_knowledge_bases_after_migrate() -> None:
	"""after_migrate: refresh the knowledge bases. A failure, such as no GitHub access, does not stop the migrate."""
	if not frappe.db.get_single_value("Flow Knowledge Settings", "embedding_model"):
		print("Investigator knowledge bases: skipped, Flow Knowledge Settings has no embedding model.")
		return

	try:
		print(f"Investigator knowledge bases: {load_knowledge_bases()}")
	except Exception as error:
		print(f"Investigator knowledge bases: not loaded. {error}")


def get_central_documents() -> dict[str, str]:
	"""Central's Markdown documents for people. Instructions for coding agents are not included."""
	root = Path(frappe.get_app_source_path("central"))
	return {
		str(path.relative_to(root)): path.read_text(encoding="utf-8")
		for pattern in CENTRAL_PATTERNS
		for path in sorted(root.glob(pattern))
		if not SKIPPED_FOLDERS & set(path.relative_to(root).parts)
	}


def get_pilot_documents() -> dict[str, str]:
	"""The README, the specification, and the handbook of Pilot from GitHub."""
	tree = _get_github(
		f"https://api.github.com/repos/{PILOT_REPOSITORY}/git/trees/{PILOT_REFERENCE}?recursive=1"
	).json()
	paths = [
		item["path"]
		for item in tree["tree"]
		if item["path"] in {"README.md", "SPEC.md"}
		or (item["path"].startswith("docs/") and item["path"].endswith(".md"))
	]
	return {
		path: _get_github(
			f"https://raw.githubusercontent.com/{PILOT_REPOSITORY}/{PILOT_REFERENCE}/{path}"
		).text
		for path in paths
	}


def _get_github(url: str) -> requests.Response:
	response = requests.get(url, timeout=GITHUB_TIMEOUT_SECONDS)
	response.raise_for_status()
	return response


def _sync(knowledge_base: str, documents: dict[str, str]) -> dict[str, int]:
	knowledge = Knowledge(knowledge_base)
	documents = {title: as_knowledge_text(content) for title, content in documents.items()}
	sources = {
		source.title: source
		for source in frappe.get_all(
			"Flow Knowledge Source",
			filters={"knowledge_base": knowledge.name},
			fields=["name", "title", "content"],
		)
	}

	counts = {"added": 0, "reloaded": 0, "deleted": 0, "unchanged": 0}
	for title, source in sources.items():
		if documents.get(title) != source.content:
			# A deploy step, not a user: the sources belong to the knowledge base.
			frappe.delete_doc("Flow Knowledge Source", source.name, ignore_permissions=True)
			counts["deleted" if title not in documents else "reloaded"] += 1

	for title, content in documents.items():
		if title in sources and sources[title].content == content:
			counts["unchanged"] += 1
		elif content.strip():
			knowledge.add_text(content, title=title)
			counts["added"] += title not in sources

	return counts


def as_knowledge_text(content: str) -> str:
	"""Flow saves a source through the HTML sanitizer, which drops the text after a tag-like `<site>`."""
	return content.replace("<", "&lt;").replace(">", "&gt;")
