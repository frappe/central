import frappe
from frappe.tests import UnitTestCase

from central.deploy.config import DEFAULT_SIZE, find_containerfile, get_deploy_config


class UnitTestDeployConfig(UnitTestCase):
	def test_a_repository_without_a_config_deploys_at_growth(self):
		self.assertEqual(DEFAULT_SIZE, "Growth")
		self.assertEqual(get_deploy_config(None).machine.size, "Growth")
		self.assertEqual(get_deploy_config("[machine]\n").machine.size, "Growth")

	def test_the_machine_size_is_read(self):
		self.assertEqual(get_deploy_config('[machine]\nsize = "Pro"\n').machine.size, "Pro")

	def test_bad_configs_are_refused(self):
		for config in (
			"[machine",
			'machine = "big"',
			"[machine]\nteam = 1",
			"[machine]\nsize = 4",
			"[machine]\ncpu_millicores = 4000",
			'[build]\nlanguage = "python"',
		):
			with self.subTest(config=config), self.assertRaises(frappe.ValidationError):
				get_deploy_config(config)

	def test_the_build_file_is_found_the_way_buildah_finds_it(self):
		def entry(name: str, type: str = "file") -> dict:
			return {"name": name, "type": type}

		self.assertEqual(find_containerfile([entry("Dockerfile"), entry("Containerfile")]), "Containerfile")
		self.assertEqual(find_containerfile([entry("README.md"), entry("Dockerfile")]), "Dockerfile")
		for root in (
			[entry("README.md")],
			[entry("dockerfile")],
			[entry("DockerFile")],
			[entry("containerfile")],
			[entry("Dockerfile", "dir")],
			[entry("Dockerfile", "symlink")],
			[entry("Containerfile", "symlink"), entry("Dockerfile")],
			[entry("Dockerfile.prod")],
		):
			with self.subTest(root=root), self.assertRaises(frappe.ValidationError):
				find_containerfile(root)
