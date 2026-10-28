"""Checks that the shared fixtures isolate tests from user data and network."""
import socket

import pytest

import config


def test_config_path_points_to_temp_dir(isolated_data_dir):
    assert config.CONFIG_PATH == str(isolated_data_dir / "config.json")


def test_outbound_connection_is_blocked():
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.create_connection(("example.com", 443))
