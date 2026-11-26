from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from central.deploy.config import find_containerfile, get_deploy_config


class UnitTestDeployConfig(UnitTestCase):
	def test_a_repository_without_a_size_deploys_at_the_settings_default(self):
		with patch("frappe.db.get_single_value", return_value="Starter"):
			self.assertEqual(get_deploy_config(None).get_machine_size(), "Starter")
			self.assertEqual(get_deploy_config("[machine]\n").get_machine_size(), "Starter")
			self.assertEqual(get_deploy_config('[machine]\nsize = "Pro"\n').get_machine_size(), "Pro")

	def test_no_default_size_fails_loudly(self):
		with (
			patch("frappe.db.get_single_value", return_value=None),
			self.assertRaises(frappe.ValidationError),
		):
			get_deploy_config(None).get_machine_size()

	def test_the_machine_size_is_read(self):
		self.assertEqual(get_deploy_config('[machine]\nsize = "Pro"\n').machine.size, "Pro")

	def test_without_a_health_path_any_answer_will_do_within_a_minute(self):
		health = get_deploy_config(None).health
		self.assertEqual((health.path, health.timeout), ("", 60))

	def test_the_health_check_is_read(self):
		health = get_deploy_config('[health]\npath = "/api/health"\ntimeout = 120\n').health
		self.assertEqual((health.path, health.timeout), ("/api/health", 120))

	def test_bad_configs_are_refused(self):
		for config in (
			"[machine",
			'machine = "big"',
			"[machine]\nteam = 1",
			"[machine]\nsize = 4",
			"[machine]\ncpu_millicores = 4000",
			'[build]\nlanguage = "python"',
			'[health]\npath = "health"',
			'[health]\npath = "/a b"',
			"[health]\ntimeout = 0",
			"[health]\ntimeout = 601",
			'[health]\ntimeout = "60"',
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
