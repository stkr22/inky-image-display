"""Sync-specific utility modules.

Color analysis lives in ``inky_image_display_shared.utils`` so utility
scripts can call it directly; image resize/crop runs inside the API and
sync workers reach it via ``DisplayAPIClient.process_image``.
"""
