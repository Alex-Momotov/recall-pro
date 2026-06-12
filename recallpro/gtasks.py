"""Google Tasks API client. The daemon owns the "Revisions" list outright.

Note: the Tasks API stores `due` date-only — any time portion is discarded
by Google, so tasks appear as all-day items.
"""
from __future__ import annotations

from datetime import date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import config

SCOPES = ["https://www.googleapis.com/auth/tasks"]


def load_credentials() -> Credentials | None:
    if not config.TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(config.TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            return None
        config.TOKEN_PATH.write_text(creds.to_json())
    return creds if creds.valid else None


def run_oauth_flow() -> Credentials:
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    config.TOKEN_PATH.write_text(creds.to_json())
    return creds


def get_service():
    creds = load_credentials()
    if creds is None:
        raise RuntimeError("Google not authenticated — run `recallpro setup`")
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def ensure_list(service) -> str:
    resp = service.tasklists().list(maxResults=100).execute()
    for tl in resp.get("items", []):
        if tl["title"] == config.GTASKS_LIST_TITLE:
            return tl["id"]
    created = service.tasklists().insert(
        body={"title": config.GTASKS_LIST_TITLE}).execute()
    return created["id"]


def fetch_tasks(service, list_id: str) -> list[dict]:
    """All tasks in the list, including completed/hidden ones (a checked-off
    task becomes hidden and would otherwise be invisible to the daemon)."""
    tasks: list[dict] = []
    page_token = None
    while True:
        resp = service.tasks().list(
            tasklist=list_id, showCompleted=True, showHidden=True,
            maxResults=100, pageToken=page_token).execute()
        tasks.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return tasks


def due_rfc3339(d: date) -> str:
    return d.isoformat() + "T00:00:00.000Z"


def insert_task(service, list_id: str, title: str, notes: str, due: date) -> str:
    body = {"title": title, "notes": notes, "due": due_rfc3339(due)}
    return service.tasks().insert(tasklist=list_id, body=body).execute()["id"]


def patch_task(service, list_id: str, task_id: str, fields: dict) -> None:
    try:
        service.tasks().patch(
            tasklist=list_id, task=task_id, body=fields).execute()
    except HttpError as e:
        if e.resp.status not in (404, 410):
            raise


def delete_task(service, list_id: str, task_id: str) -> None:
    try:
        service.tasks().delete(tasklist=list_id, task=task_id).execute()
    except HttpError as e:
        if e.resp.status not in (404, 410):
            raise
