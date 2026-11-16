import frappe
from frappe.tests import UnitTestCase

from central.deploy.config import find_containerfile, get_machine_specs


class UnitTestDeployConfig(UnitTestCase):
	def test_a_repository_without_a_config_keeps_the_defaults(self):
		self.assertEqual(get_machine_specs(None), {})
		self.assertEqual(get_machine_specs('[build]\nlanguage = "python"\n'), {})

	def test_the_machine_table_is_read(self):
		self.assertEqual(
			get_machine_specs("[machine]\ncpu_millicores = 4000\ndisk_mib = 40960\n"),
			{"cpu_millicores": 4000, "disk_mib": 40960},
		)

	def test_bad_configs_are_refused(self):
		for config in (
			"[machine",
			'machine = "big"',
			"[machine]\nteam = 1",
			"[machine]\ncpu_millicores = 50",
			"[machine]\nmemory_mib = 4096.5",
			'[machine]\nmemory_mib = "4096"',
			"[machine]\ndisk_mib = true",
		):
			with self.subTest(config=config), self.assertRaises(frappe.ValidationError):
				get_machine_specs(config)

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
