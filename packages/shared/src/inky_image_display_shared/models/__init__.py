"""SQLModel database models for Inky Image Display."""

from .app_setting import AppSetting
from .device import Device, DeviceDisplayState
from .device_profile import DeviceProfile
from .gemini_sync_job import GeminiSyncJob
from .grid import Grid, GridDevice
from .image import Image
from .immich_sync_job import ImmichSyncJob, SyncStrategy
from .motd import MotdConfig, MotdDeviceAssignment, MotdMessage, MotdScreen
from .prompt_block import PromptBlock
from .prompt_preset import PromptPreset

__all__ = [
    "AppSetting",
    "Device",
    "DeviceDisplayState",
    "DeviceProfile",
    "GeminiSyncJob",
    "Grid",
    "GridDevice",
    "Image",
    "ImmichSyncJob",
    "MotdConfig",
    "MotdDeviceAssignment",
    "MotdMessage",
    "MotdScreen",
    "PromptBlock",
    "PromptPreset",
    "SyncStrategy",
]
