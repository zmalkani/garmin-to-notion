"""Sync Garmin activities into the user's existing NEW training log Notion database."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from garminconnect import Garmin as GarminClient
from notion_client import Client as NotionClient

from garmin_to_notion.config import Settings
from garmin_to_notion.formatters import gmt_to_local
from garmin_to_notion.notion_helpers import fetch_all_pages

logger = logging.getLogger(__name__)

TYPE_MAP = {
    "strength_training": "Lift",
    "strength": "Lift",
    "functional_training": "Lift",
    "weight_training": "Lift",
    "hiking": "Hike",
    "walking": "Hike",
    "speed_walking": "Hike",
    "casual_walking": "Hike",
    "skiing": "Ski",
    "resort_skiing_snowboarding": "Ski",
    "cross_country_skiing": "Ski",
    "snowboarding": "Ski",
    "cycling": "Bike",
    "indoor_cycling": "Bike",
    "mountain_biking": "Bike",
    "gravel_cycling": "Bike",
    "e_biking": "Bike",
    "virtual_ride": "Bike",
    "indoor_rowing": "Erg",
    "rowing": "Row",
    "rowing_v2": "Row",
    "running": "Run",
    "street_running": "Run",
    "trail_running": "Run",
    "track_running": "Run",
    "treadmill_running": "Run",
    "indoor_running": "Run",
}


def _garmin_type(activity: dict) -> str | None:
    key = str(
        (activity.get("activityType") or {}).get("typeKey", "")
    ).strip().lower().replace(" ", "_")

    if key in TYPE_MAP:
        return TYPE_MAP[key]

    name = str(activity.get("activityName", "")).lower()
    if "erg" in name or "indoor row" in name:
        return "Erg"
    if "row" in name:
        return "Row"
    if "ski" in name:
        return "Ski"
    if "hike" in name:
        return "Hike"
    if any(x in name for x in ("lift", "strength", "weight")):
        return "Lift"
    if any(x in name for x in ("bike", "cycling")):
        return "Bike"
    if "run" in name:
        return "Run"
    return None


def _build_properties(activity: dict, settings: Settings) -> dict:
    activity_id = activity.get("activityId")
    activity_name = activity.get("activityName", "Unnamed Activity")
    activity_type = _garmin_type(activity)

    local_start = gmt_to_local(activity.get("startTimeGMT"), settings.timezone)
    duration_seconds = float(activity.get("duration") or 0)
    local_end = local_start + timedelta(seconds=duration_seconds)
    distance_km = round(float(activity.get("distance") or 0) / 1000, 2)

    props = {
        "Name": {"title": [{"text": {"content": activity_name}}]},
        "Date": {
            "date": {
                "start": local_start.isoformat(),
                "end": local_end.isoformat(),
            }
        },
        "Dist. (km)": {"number": distance_km},
        "volume (h)": {"number": round(duration_seconds / 3600, 4)},
        "Garmin ID": {"number": activity_id},
        "Activity link": {
            "url": f"https://connect.garmin.com/modern/activity/{activity_id}"
        },
    }

    if activity_type:
        props["Type"] = {"select": {"name": activity_type}}

    return props


def _date_needs_update(page: dict, expected: dict) -> bool:
    date_prop = page.get("properties", {}).get("Date", {})
    current = date_prop.get("date") or {}
    return (
        current.get("start") != expected["start"]
        or current.get("end") != expected["end"]
    )


def sync_activities(
    garmin: GarminClient,
    notion: NotionClient,
    settings: Settings,
) -> None:
    """Sync Garmin activities into NEW training log."""
    activities = garmin.get_activities(0, settings.fetch_limit)
    logger.info("Fetched %d activities from Garmin", len(activities))

    existing_pages = fetch_all_pages(
        notion,
        settings.activities_db_id,
        filter={"property": "Garmin ID", "number": {"is_not_empty": True}},
    )
    existing_ids = {
        page.get("properties", {}).get("Garmin ID", {}).get("number")
        for page in existing_pages
    }
    existing_ids.discard(None)
    pages_by_id = {
        page.get("properties", {}).get("Garmin ID", {}).get("number"): page
        for page in existing_pages
    }
    logger.info("Found %d existing Garmin activities in Notion", len(existing_ids))

    created = updated = skipped = 0

    for activity in activities:
        activity_id = activity.get("activityId")
        properties = _build_properties(activity, settings)

        if activity_id in existing_ids:
            page = pages_by_id.get(activity_id)
            if page and _date_needs_update(page, properties["Date"]["date"]):
                notion.pages.update(
                    page_id=page["id"],
                    properties={"Date": properties["Date"]},
                )
                updated += 1
                time.sleep(0.4)
            else:
                skipped += 1
            continue

        notion.pages.create(
            parent={"database_id": settings.activities_db_id},
            properties=properties,
        )
        existing_ids.add(activity_id)
        created += 1
        time.sleep(0.4)

    logger.info(
        "Training log sync complete: %d created, %d updated, %d unchanged",
        created,
        updated,
        skipped,
    )
