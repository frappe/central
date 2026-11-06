from types import SimpleNamespace
from unittest import TestCase

import frappe
import yaml

from central.integrations.images import get_minimum_shape, is_shape_enough
from central.resource_actions import _get_user_data, _validate_app_size

SHAPE = {"cpu_millicores": 1000, "memory_mib": 1024, "disk_mib": 10240}
APP_IMAGE = {"tags": {"purpose": "one-click", "application": "redis"}, "rootfs_size_mib": 4096}
UBUNTU_IMAGE = {"tags": {"purpose": "base"}, "rootfs_size_mib": 4096}


APP_INPUTS = [
	{"name": "domain", "label": "Domain", "type": "domain", "required": False},
	{"name": "admin_email", "label": "Admin email", "type": "email", "required": True},
	{"name": "admin_password", "label": "Admin password", "type": "password"},
]
EMAIL = {"admin_email": "me@example.com"}


def requirements(inputs: list[dict] | None = None, **minimum: int) -> dict:
	return {
		"inputs": inputs or [],
		"minimum_size": {"cpu_millicores": 500, "memory_mib": 512, "disk_mib": 5120, **minimum},
		"ports": [],
	}


def server_input(**values) -> SimpleNamespace:
	return SimpleNamespace(**{"region": "region-a", "user_data": "", "app_inputs": {}, **values})


class TestAppSize(TestCase):
	def test_a_big_enough_server_passes(self) -> None:
		_validate_app_size(APP_IMAGE, requirements(), SHAPE)

	def test_a_server_smaller_than_the_app_is_refused(self) -> None:
		for minimum in ({"cpu_millicores": 2000}, {"memory_mib": 2048}, {"disk_mib": 20480}):
			with self.subTest(minimum=minimum), self.assertRaises(frappe.ValidationError):
				_validate_app_size(APP_IMAGE, requirements(**minimum), SHAPE)

	def test_a_server_without_app_requirements_is_not_checked(self) -> None:
		_validate_app_size(UBUNTU_IMAGE, None, {**SHAPE, "cpu_millicores": 100})

	def test_a_plan_must_reach_the_app_minimum(self) -> None:
		minimum = get_minimum_shape(APP_IMAGE, requirements())

		self.assertEqual(minimum, {"cpu_millicores": 500, "memory_mib": 512, "disk_mib": 5120})
		self.assertTrue(is_shape_enough({"Compute": 0.5, "Memory": 0.5, "Disk": 5}, minimum))
		self.assertFalse(is_shape_enough({"Compute": 0.25, "Memory": 1, "Disk": 10}, minimum))

	def test_the_image_disk_counts_when_it_is_bigger(self) -> None:
		image = {**APP_IMAGE, "rootfs_size_mib": 8192}

		self.assertEqual(get_minimum_shape(image, requirements())["disk_mib"], 8192)


class TestAppUserData(TestCase):
	def test_answers_are_written_to_inputs_env_shell_quoted(self) -> None:
		password = "it's $(reboot) #1"
		answers = {"admin_password": password, "admin_email": "me@example.com", "domain": "app.example.com"}

		user_data = _get_user_data(server_input(app_inputs=answers), requirements(APP_INPUTS))

		self.assertTrue(user_data.startswith("#cloud-config\n"))
		[file] = yaml.safe_load(user_data)["write_files"]
		self.assertEqual((file["path"], file["permissions"]), ("/etc/one-click/inputs.env", "0600"))
		self.assertEqual(
			file["content"],
			"DOMAIN=app.example.com\nADMIN_EMAIL=me@example.com\nADMIN_PASSWORD='it'\"'\"'s $(reboot) #1'\n",
		)

	def test_a_blank_answer_is_left_for_the_server(self) -> None:
		user_data = _get_user_data(
			server_input(app_inputs={**EMAIL, "admin_password": "  "}), requirements(APP_INPUTS)
		)

		self.assertEqual(
			yaml.safe_load(user_data)["write_files"][0]["content"], "ADMIN_EMAIL=me@example.com\n"
		)

	def test_an_app_without_answers_takes_no_user_data(self) -> None:
		self.assertEqual(_get_user_data(server_input(), requirements()), "")

	def test_invalid_answers_are_refused(self) -> None:
		for answers, message in (
			({}, "Admin email is required"),
			({"admin_email": "not an email"}, "not a valid Email Address"),
			({**EMAIL, "domain": "not a domain"}, "Domain must be a domain name"),
			({**EMAIL, "domain": "a" * 300 + ".com"}, "Domain must be at most 255 characters"),
			({**EMAIL, "admin_password": "password123"}, "Admin password is too easy to guess"),
			({**EMAIL, "admin_password": "a long line\nwith a break"}, "only printable characters"),
			({**EMAIL, "admin_password": "a long line\twith a tab"}, "only printable characters"),
			({**EMAIL, "shell": "rm -rf /"}, "This app has no setting shell"),
		):
			with self.subTest(answers=answers), self.assertRaisesRegex(frappe.ValidationError, message):
				_get_user_data(server_input(app_inputs=answers), requirements(APP_INPUTS))

	def test_an_input_name_must_be_a_shell_variable(self) -> None:
		inputs = [{"name": "bad-name", "label": "Bad"}]

		with self.assertRaisesRegex(frappe.ValidationError, "not a valid shell variable name"):
			_get_user_data(server_input(app_inputs={"bad-name": "value"}), requirements(inputs))

	def test_an_app_refuses_its_own_user_data(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			_get_user_data(server_input(user_data="#!/bin/sh"), requirements())

	def test_any_other_server_refuses_app_settings(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			_get_user_data(server_input(app_inputs={"password": "a" * 12}), None)

	def test_any_other_server_keeps_the_customer_user_data(self) -> None:
		self.assertEqual(_get_user_data(server_input(user_data="#!/bin/sh"), None), "#!/bin/sh")
