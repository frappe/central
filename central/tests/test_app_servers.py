from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from central.integrations.images import get_minimum_shape, is_shape_enough
from central.resource_actions import _get_user_data, _validate_app_size

SHAPE = {"cpu_millicores": 1000, "memory_mib": 1024, "disk_mib": 10240}
APP_IMAGE = {"tags": {"purpose": "one-click", "application": "redis"}, "rootfs_size_mib": 4096}
UBUNTU_IMAGE = {"tags": {"purpose": "base"}, "rootfs_size_mib": 4096}


def requirements(**minimum: int) -> dict:
	return {
		"inputs": [],
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


@patch("central.resource_actions.frappe.get_doc")
class TestAppUserData(TestCase):
	def test_an_app_takes_its_user_data_from_cargo(self, _region) -> None:
		with patch(
			"central.resource_actions.CargoClient.get_app_user_data", return_value="#cloud-config\n"
		) as user_data:
			result = _get_user_data(server_input(app_inputs={"password": "a" * 12}), APP_IMAGE, None)

		self.assertEqual(result, "#cloud-config\n")
		user_data.assert_called_once_with("redis", {"password": "a" * 12})

	def test_an_app_refuses_its_own_user_data(self, _region) -> None:
		with self.assertRaises(frappe.ValidationError):
			_get_user_data(server_input(user_data="#!/bin/sh"), APP_IMAGE, None)

	def test_any_other_server_refuses_app_settings(self, _region) -> None:
		with self.assertRaises(frappe.ValidationError):
			_get_user_data(server_input(app_inputs={"password": "a" * 12}), UBUNTU_IMAGE, None)

	def test_a_restored_app_server_takes_no_app_user_data(self, _region) -> None:
		with patch("central.resource_actions.CargoClient.get_app_user_data") as user_data:
			self.assertEqual(_get_user_data(server_input(), APP_IMAGE, "snapshot-1"), "")

		user_data.assert_not_called()
