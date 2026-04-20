"""Sync jobs view: list with active toggle + create/edit form."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import flet as ft

from inky_image_display_ui.api_client import ApiError
from inky_image_display_ui.formatting import format_datetime
from inky_image_display_ui.session import get_api_client

if TYPE_CHECKING:
    from inky_image_display_ui.api_client import ApiClient

logger = logging.getLogger(__name__)

_STRATEGIES = ["RANDOM", "SMART"]
_MIN_COUNT = 1
_MAX_COUNT = 1000
_FAVORITE_OPTIONS = [("", "Any"), ("true", "Favorites only"), ("false", "Non-favorites only")]
_RATING_OPTIONS = [("", "Any"), *[(str(i), f">= {i}") for i in range(6)]]


async def build_list(page: ft.Page) -> ft.Control:
    """Build the sync-jobs list view."""
    api = get_api_client(page)
    device_map = await _load_device_map(api)
    container = ft.Column(expand=True, spacing=8, scroll=ft.ScrollMode.AUTO)

    async def reload() -> None:
        try:
            jobs = await api.list_sync_jobs()
        except ApiError as exc:
            _snack(page, f"Failed to load sync jobs: {exc.detail or exc}")
            return
        container.controls.clear()
        if not jobs:
            container.controls.append(ft.Text("No sync jobs yet.", italic=True))
        else:
            for job in jobs:
                container.controls.append(_row(page, api, job, device_map, reload))
        page.update()

    new_button = ft.FilledButton(
        "New job",
        icon=ft.Icons.ADD,
        on_click=lambda _e: page.go("/sync-jobs/new"),
    )
    refresh_button = ft.IconButton(
        icon=ft.Icons.REFRESH,
        tooltip="Refresh",
        on_click=lambda _e: asyncio.create_task(reload()),
    )

    await reload()

    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Sync jobs", size=22, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    refresh_button,
                    new_button,
                ]
            ),
            container,
        ],
        expand=True,
    )


def _row(
    page: ft.Page,
    api: ApiClient,
    job: dict[str, Any],
    device_map: dict[str, str],
    on_changed: Any,
) -> ft.Control:
    job_id = UUID(job["id"])
    active_switch = ft.Switch(value=bool(job.get("is_active")), tooltip="Active")

    async def toggle_active() -> None:
        new_value = bool(active_switch.value)
        try:
            await api.update_sync_job(job_id, {"is_active": new_value})
        except ApiError as exc:
            _snack(page, f"Toggle failed: {exc.detail or exc}")
            active_switch.value = not new_value
            page.update()
            return
        _snack(page, "Updated")

    async def delete() -> None:
        if not await _confirm(page, f"Delete sync job '{job['name']}'?"):
            return
        try:
            await api.delete_sync_job(job_id)
        except ApiError as exc:
            _snack(page, f"Delete failed: {exc.detail or exc}")
            return
        await on_changed()

    active_switch.on_change = lambda _e: asyncio.create_task(toggle_active())

    target_name = device_map.get(job["target_device_id"], job["target_device_id"])

    return ft.Card(
        content=ft.Container(
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(job["name"], size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                f"{job['strategy']} · count={job['count']} · → {target_name}",
                                size=12,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Text(f"Updated: {format_datetime(job.get('updated_at'))}", size=11),
                        ],
                        tight=True,
                        expand=True,
                    ),
                    active_switch,
                    ft.IconButton(
                        icon=ft.Icons.EDIT,
                        tooltip="Edit",
                        on_click=lambda _e: page.go(f"/sync-jobs/{job['id']}"),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="Delete",
                        on_click=lambda _e: asyncio.create_task(delete()),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
        )
    )


async def build_form(page: ft.Page, *, job_id: str | None) -> ft.Control:  # noqa: PLR0915
    """Build the create/edit form. ``job_id=None`` means create."""
    api = get_api_client(page)
    devices = await _load_devices(api)
    device_options = [ft.dropdown.Option(key=d["id"], text=d.get("device_id") or d["id"]) for d in devices]

    job: dict[str, Any] = {}
    if job_id is not None:
        try:
            job = await api.get_sync_job(UUID(job_id))
        except ApiError as exc:
            _snack(page, f"Load failed: {exc.detail or exc}")
            return ft.Text("Could not load sync job.", color=ft.Colors.ERROR)

    name_field = ft.TextField(label="Name", value=job.get("name") or "")
    strategy_field = ft.Dropdown(
        label="Strategy",
        value=job.get("strategy") or "RANDOM",
        options=[ft.dropdown.Option(s) for s in _STRATEGIES],
    )
    query_field = ft.TextField(
        label="Query (SMART strategy)",
        value=job.get("query") or "",
        disabled=(strategy_field.value != "SMART"),
    )

    def on_strategy_change() -> None:
        query_field.disabled = strategy_field.value != "SMART"
        page.update()

    strategy_field.on_select = lambda _e: on_strategy_change()

    target_dropdown = ft.Dropdown(
        label="Target device",
        options=device_options,
        value=job.get("target_device_id") or (devices[0]["id"] if devices else None),
    )
    count_field = ft.TextField(
        label="Count (1-1000)",
        value=str(job.get("count") or 10),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=180,
    )
    random_pick = ft.Switch(label="Random pick", value=bool(job.get("random_pick")))
    overfetch_slider = ft.Slider(
        min=1, max=10, divisions=9, value=float(job.get("overfetch_multiplier") or 3), label="Overfetch x{value}"
    )
    albums_field = ft.TextField(
        label="Album IDs (one per line)",
        value="\n".join(job.get("album_ids") or []),
        multiline=True,
        min_lines=1,
        max_lines=4,
    )
    persons_field = ft.TextField(
        label="Person IDs (one per line)",
        value="\n".join(job.get("person_ids") or []),
        multiline=True,
        min_lines=1,
        max_lines=4,
    )
    tags_field = ft.TextField(
        label="Tag IDs (one per line)",
        value="\n".join(job.get("tag_ids") or []),
        multiline=True,
        min_lines=1,
        max_lines=4,
    )
    favorite_field = ft.Dropdown(
        label="Favorite filter",
        value=_bool_to_option(job.get("is_favorite")),
        options=[ft.dropdown.Option(key=k, text=t) for k, t in _FAVORITE_OPTIONS],
    )
    city_field = ft.TextField(label="City", value=job.get("city") or "")
    state_field = ft.TextField(label="State/Region", value=job.get("state") or "")
    country_field = ft.TextField(label="Country", value=job.get("country") or "")
    taken_after_field = ft.TextField(label="Taken after (YYYY-MM-DD)", value=_date_str(job.get("taken_after")))
    taken_before_field = ft.TextField(label="Taken before (YYYY-MM-DD)", value=_date_str(job.get("taken_before")))
    rating_field = ft.Dropdown(
        label="Rating",
        value=str(job["rating"]) if isinstance(job.get("rating"), int) else "",
        options=[ft.dropdown.Option(key=k, text=t) for k, t in _RATING_OPTIONS],
    )
    color_slider = ft.Slider(
        min=0.0, max=1.0, divisions=20, value=float(job.get("min_color_score") or 0.5), label="Color ≥ {value}"
    )
    vibrancy_slider = ft.Slider(
        min=0.0, max=1.0, divisions=20, value=float(job.get("min_vibrancy_score") or 0.2), label="Vibrancy ≥ {value}"
    )
    active_switch = ft.Switch(label="Active", value=bool(job.get("is_active", True)))

    error_text = ft.Text("", color=ft.Colors.ERROR)

    async def save() -> None:
        body = _collect_form(
            name_field=name_field,
            strategy_field=strategy_field,
            query_field=query_field,
            target_dropdown=target_dropdown,
            count_field=count_field,
            random_pick=random_pick,
            overfetch_slider=overfetch_slider,
            albums_field=albums_field,
            persons_field=persons_field,
            tags_field=tags_field,
            favorite_field=favorite_field,
            city_field=city_field,
            state_field=state_field,
            country_field=country_field,
            taken_after_field=taken_after_field,
            taken_before_field=taken_before_field,
            rating_field=rating_field,
            color_slider=color_slider,
            vibrancy_slider=vibrancy_slider,
            active_switch=active_switch,
            is_edit=job_id is not None,
        )
        if isinstance(body, str):
            error_text.value = body
            page.update()
            return
        try:
            if job_id is None:
                await api.create_sync_job(body)
            else:
                await api.update_sync_job(UUID(job_id), body)
        except ApiError as exc:
            error_text.value = f"Save failed: {exc.detail or exc}"
            page.update()
            return
        _snack(page, "Saved")
        page.go("/sync-jobs")

    title = "New sync job" if job_id is None else "Edit sync job"

    return ft.Column(
        [
            ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda _e: page.go("/sync-jobs")),
                    ft.Text(title, size=22, weight=ft.FontWeight.BOLD),
                ]
            ),
            ft.Column(
                [
                    name_field,
                    ft.Row([strategy_field, query_field]),
                    target_dropdown,
                    ft.Row([count_field, random_pick]),
                    ft.Text("Overfetch multiplier"),
                    overfetch_slider,
                    albums_field,
                    persons_field,
                    tags_field,
                    ft.Row([favorite_field, rating_field]),
                    ft.Row([city_field, state_field, country_field]),
                    ft.Row([taken_after_field, taken_before_field]),
                    ft.Text("Minimum color score"),
                    color_slider,
                    ft.Text("Minimum vibrancy score"),
                    vibrancy_slider,
                    active_switch,
                    error_text,
                    ft.Row(
                        [
                            ft.TextButton("Cancel", on_click=lambda _e: page.go("/sync-jobs")),
                            ft.Container(expand=True),
                            ft.FilledButton(
                                "Save", icon=ft.Icons.SAVE, on_click=lambda _e: asyncio.create_task(save())
                            ),
                        ]
                    ),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        ],
        expand=True,
    )


def _collect_form(  # noqa: PLR0911, PLR0913
    *,
    name_field: ft.TextField,
    strategy_field: ft.Dropdown,
    query_field: ft.TextField,
    target_dropdown: ft.Dropdown,
    count_field: ft.TextField,
    random_pick: ft.Switch,
    overfetch_slider: ft.Slider,
    albums_field: ft.TextField,
    persons_field: ft.TextField,
    tags_field: ft.TextField,
    favorite_field: ft.Dropdown,
    city_field: ft.TextField,
    state_field: ft.TextField,
    country_field: ft.TextField,
    taken_after_field: ft.TextField,
    taken_before_field: ft.TextField,
    rating_field: ft.Dropdown,
    color_slider: ft.Slider,
    vibrancy_slider: ft.Slider,
    active_switch: ft.Switch,
    is_edit: bool,
) -> dict[str, Any] | str:
    """Validate + pack the form values into a request dict, or return an error string."""
    if not name_field.value:
        return "Name is required"
    if not target_dropdown.value:
        return "Target device is required"
    try:
        count = int(count_field.value or 10)
    except ValueError:
        return "Count must be an integer"
    if not _MIN_COUNT <= count <= _MAX_COUNT:
        return f"Count must be between {_MIN_COUNT} and {_MAX_COUNT}"
    strategy = strategy_field.value or "RANDOM"
    if strategy == "SMART" and not (query_field.value or "").strip():
        return "Query is required when strategy is SMART"

    taken_after = _parse_date(taken_after_field.value)
    if taken_after_field.value and taken_after is None:
        return "Taken-after must be YYYY-MM-DD"
    taken_before = _parse_date(taken_before_field.value)
    if taken_before_field.value and taken_before is None:
        return "Taken-before must be YYYY-MM-DD"

    rating_value: int | None = None
    if rating_field.value:
        try:
            rating_value = int(rating_field.value)
        except ValueError:
            return "Rating must be an integer"

    body: dict[str, Any] = {
        "name": name_field.value,
        "strategy": strategy,
        "query": (query_field.value or None) if strategy == "SMART" else None,
        "target_device_id": target_dropdown.value,
        "count": count,
        "random_pick": bool(random_pick.value),
        "overfetch_multiplier": int(overfetch_slider.value or 3),
        "album_ids": _split_lines(albums_field.value),
        "person_ids": _split_lines(persons_field.value),
        "tag_ids": _split_lines(tags_field.value),
        "is_favorite": _option_to_bool(favorite_field.value),
        "city": city_field.value or None,
        "state": state_field.value or None,
        "country": country_field.value or None,
        "taken_after": taken_after.isoformat() if taken_after else None,
        "taken_before": taken_before.isoformat() if taken_before else None,
        "rating": rating_value,
        "min_color_score": float(color_slider.value or 0.0),
        "min_vibrancy_score": float(vibrancy_slider.value or 0.0),
        "is_active": bool(active_switch.value),
    }
    # On create, the target_device_id must be present; drop None list fields to avoid API surprises.
    if not is_edit and body.get("target_device_id") is None:
        return "Target device is required"
    return body


def _split_lines(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [line.strip() for line in value.splitlines() if line.strip()]
    return items or None


def _option_to_bool(value: str | None) -> bool | None:
    if not value:
        return None
    return value == "true"


def _bool_to_option(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _date_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    return ""


async def _load_devices(api: ApiClient) -> list[dict[str, Any]]:
    try:
        return await api.list_devices()
    except ApiError:
        logger.exception("Failed to load device list for sync-jobs view")
        return []


async def _load_device_map(api: ApiClient) -> dict[str, str]:
    devices = await _load_devices(api)
    return {d["id"]: d.get("device_id") or d["id"] for d in devices}


async def _confirm(page: ft.Page, message: str) -> bool:
    result: dict[str, bool] = {"value": False}
    event = asyncio.Event()

    def close(value: bool) -> None:
        result["value"] = value
        event.set()
        page.pop_dialog()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirm"),
        content=ft.Text(message),
        actions=[
            ft.TextButton("Cancel", on_click=lambda _e: close(False)),
            ft.FilledButton("Confirm", on_click=lambda _e: close(True)),
        ],
    )
    page.show_dialog(dialog)
    await event.wait()
    return result["value"]


def _snack(page: ft.Page, message: str) -> None:
    page.show_dialog(ft.SnackBar(content=ft.Text(message), duration=3000))
