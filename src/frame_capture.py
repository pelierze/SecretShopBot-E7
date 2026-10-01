"""Capture in memory when supported, with a legacy screenshot fallback."""
from .core.device import UnifiedDevice
from .image_matcher import read_image


def capture_image(device, path, reader=read_image):
    if isinstance(device, UnifiedDevice):
        return device.capture_frame()
    if not device.screenshot(str(path)):
        return None
    return reader(str(path))
