"""Shared pytest startup configuration.

Importing a Kivy widget module can select the window provider. Set the mock
provider before pytest imports any test modules (some of which import main).
"""
import os

os.environ["KIVY_UNITTEST"] = "1"

from kivy.config import Config

Config.set("kivy", "window", "mock")
Config.set("kivy", "log_level", "warning")
