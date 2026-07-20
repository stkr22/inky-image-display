"""SQLModel database models for Inky Image Display."""

from .app_setting import AppSetting
from .device import Device, DeviceDisplayState
from .device_profile import DeviceProfile
from .display_job import DisplayJob, DisplayJobSlot
from .gemini_sync_job import GeminiSyncJob
from .generation_task import GenerationTask
from .grid import Grid, GridDevice
from .image import Image
from .image_group import ImageGroup
from .immich_sync_job import ImmichSyncJob, SyncStrategy
from .prompt_block import PromptBlock
from .prompt_preset import PromptPreset
from .sync_job_run import SyncJobRun

__all__ = [
    "AppSetting",
    "Device",
    "DeviceDisplayState",
    "DeviceProfile",
    "DisplayJob",
    "DisplayJobSlot",
    "GeminiSyncJob",
    "GenerationTask",
    "Grid",
    "GridDevice",
    "Image",
    "ImageGroup",
    "ImmichSyncJob",
    "PromptBlock",
    "PromptPreset",
    "SyncJobRun",
    "SyncStrategy",
]
