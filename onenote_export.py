from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable

import msal
import requests
from bs4 import BeautifulSoup
import pandas as pd

from journal_chart_export import render_trade_chart_png
from journal_summary import summary_body_html, page_html, money

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPES = ["Notes.ReadWrite", "User.Read"]


class OneNoteError(RuntimeError):
    pass


@dataclass
class SyncResult:
    notebook_name: str
    created_trade_pages: int
    existing_trade_pages: int
    updated_summary_pages: int
    created_sections: int
    created_month_groups: int


class GraphClient:
    def __init__(self, client_id: str, authority: str, cache_path: Path):
        if not client_id or client_id.startswith("PASTE_"):
            raise OneNoteError("OneNote is not configured yet. Enter the Microsoft application (client) ID first.")
        self.client_id = client_id.strip()
        self.authority = authority.strip() or "https://login.microsoftonline.com/common"
        self.cache_path = cache_path
        self.cache = msal.SerializableTokenCache()
        if cache_path.exists():
            try:
                self.cache.deserialize(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.app = msal.PublicClientApplication(
            self.client_id,
            authority=self.authority,
            token_cache=self.cache,
        )
        self._token = None

    def _persist_cache(self):
        if self.cache.has_state_changed:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(self.cache.serialize(), encoding="utf-8")

    def token(self) -> str:
        if self._token:
            return self._token
        result = None
        accounts = self.app.get_accounts()
        if accounts:
            result = self.app.acquire_token_silent(SCOPES, account=accounts[0])
        if not result:
            # Desktop public-client flow: browser sign-in, localhost redirect.
            result = self.app.acquire_token_interactive(
                scopes=SCOPES,
                redirect_uri="http://localhost",
                prompt="select_account",
            )
        self._persist_cache()
        if not result or "access_token" not in result:
            detail = (result or {}).get("error_description") or (result or {}).get("error") or "Unknown authentication error"
            raise OneNoteError(f"Microsoft sign-in failed: {detail}")
        self._token = result["access_token"]
        return self._token

    def _request(self, method: str, path_or_url: str, *, expected=(200,), retry=True, **kwargs):
        url = path_or_url if path_or_url.startswith("http") else GRAPH_ROOT + path_or_url
        headers = kwargs.pop("headers", {})
        headers = {"Authorization": f"Bearer {self.token()}", **headers}
        for attempt in range(5):
            response = requests.request(method, url, headers=headers, timeout=90, **kwargs)
            if response.status_code in expected:
                return response
            if retry and response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                wait = response.headers.get("Retry-After")
                try:
                    seconds = max(1, int(wait)) if wait else 2 ** attempt
                except ValueError:
                    seconds = 2 ** attempt
                time.sleep(min(seconds, 30))
                continue
            try:
                detail = response.json()
            except Exception:
                detail = response.text[:1200]
            raise OneNoteError(f"Microsoft Graph {method} {url} failed ({response.status_code}): {detail}")
        raise OneNoteError(f"Microsoft Graph request failed after retries: {method} {url}")

    def get_json(self, path_or_url: str) -> dict:
        return self._request("GET", path_or_url, expected=(200,)).json()

    def list_all(self, path_or_url: str) -> list[dict]:
        items = []
        url = path_or_url
        while url:
            data = self.get_json(url)
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    def post_json(self, path: str, payload: dict) -> dict:
        return self._request(
            "POST", path, expected=(200, 201, 202),
            headers={"Content-Type": "application/json"}, json=payload,
        ).json()

    def patch_json(self, path: str, payload) -> None:
        self._request(
            "PATCH", path, expected=(204,),
            headers={"Content-Type": "application/json"}, json=payload,
        )

    def create_page_html(self, section_id: str, html: str) -> dict:
        return self._request(
            "POST", f"/me/onenote/sections/{section_id}/pages", expected=(201,),
            headers={"Content-Type": "text/html; charset=utf-8"}, data=html.encode("utf-8"),
        ).json()

    def create_page_with_image(self, section_id: str, html: str, image_bytes: bytes) -> dict:
        files = [
            ("Presentation", (None, html, "text/html; charset=utf-8")),
            ("chartImage", ("trade_chart.png", image_bytes, "image/png")),
        ]
        return self._request(
            "POST", f"/me/onenote/sections/{section_id}/pages", expected=(201,), files=files,
        ).json()

    def get_page_content(self, page_id: str) -> str:
        response = self._request(
            "GET", f"/me/onenote/pages/{page_id}/content?includeIDs=true", expected=(200,)
        )
        return response.text


def _web_url(entity: dict) -> str:
    links = entity.get("links") or {}
    web = links.get("oneNoteWebUrl") or {}
    return web.get("href") or ""


def _safe_name(name: str, limit: int = 50) -> str:
    # OneNote section/section-group forbidden characters.
    clean = re.sub(r"[?*/:<>|&#'\"%~]", "-", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:limit].rstrip()


def _month_name(ts: pd.Timestamp) -> str:
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    return f"{ts.month:02d} - {month_names[ts.month - 1]} {ts.year}"


def _day_section_name(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d - %a")


def _trade_page_title(trade: pd.Series) -> str:
    n = int(trade.get("TradeNoDay", 0) or 0)
    return f"Trade {n:02d} - {trade['Ativo']} - {trade['EntryDT']:%H:%M:%S}"


def _trade_body(trade: pd.Series) -> str:
    review_bits = []
    if str(trade.get("process_grade", "")).strip() and str(trade.get("process_grade")) != "Unreviewed":
        review_bits.append(f"<p><b>Process grade:</b> {escape(str(trade.get('process_grade')))}</p>")
    if str(trade.get("setup", "")).strip():
        review_bits.append(f"<p><b>Setup:</b> {escape(str(trade.get('setup')))}</p>")
    if str(trade.get("mistake_tag", "")).strip():
        review_bits.append(f"<p><b>Primary tag:</b> {escape(str(trade.get('mistake_tag')))}</p>")
    if str(trade.get("notes", "")).strip():
        review_bits.append(f"<p><b>Desktop notes:</b> {escape(str(trade.get('notes')))}</p>")

    return (
        "<div>"
        f"<p><b>{escape(str(trade['Side']))}</b> &nbsp; "
        f"{trade['EntryDT']:%d/%m/%Y %H:%M:%S} → {trade['ExitDT']:%H:%M:%S} &nbsp; "
        f"P/L: <b>{escape(money(float(trade['PL'])))}</b></p>"
        "<img src='name:chartImage' alt='Trade chart' width='950'/>"
        "<p style='font-size:9pt;color:#666'>Use OneNote Draw tools to write, highlight or draw directly on/around this chart. "
        "This trade page is created once and is not overwritten by later journal syncs, so your OneNote ink is preserved.</p>"
        + "".join(review_bits) +
        f"<p style='font-size:7pt;color:#999'>trade_id: {escape(str(trade['trade_id']))}</p>"
        "</div>"
    )


def _load_sync_map(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": 1, "months": {}}


def _save_sync_map(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _find_or_create_notebook(graph: GraphClient, name: str) -> tuple[dict, bool]:
    notebooks = graph.list_all("/me/onenote/notebooks?$select=id,displayName,links")
    for item in notebooks:
        if item.get("displayName", "").casefold() == name.casefold():
            return item, False
    return graph.post_json("/me/onenote/notebooks", {"displayName": name}), True


def _find_or_create_group(graph: GraphClient, notebook_id: str, name: str) -> tuple[dict, bool]:
    groups = graph.list_all(f"/me/onenote/notebooks/{notebook_id}/sectionGroups?$select=id,displayName,links")
    for item in groups:
        if item.get("displayName", "").casefold() == name.casefold():
            return item, False
    return graph.post_json(f"/me/onenote/notebooks/{notebook_id}/sectionGroups", {"displayName": name}), True


def _find_or_create_section_in_group(graph: GraphClient, group_id: str, name: str) -> tuple[dict, bool]:
    sections = graph.list_all(f"/me/onenote/sectionGroups/{group_id}/sections?$select=id,displayName,links")
    for item in sections:
        if item.get("displayName", "").casefold() == name.casefold():
            return item, False
    return graph.post_json(f"/me/onenote/sectionGroups/{group_id}/sections", {"displayName": name}), True


def _generated_id_for_data_id(content_html: str, data_id: str) -> str | None:
    soup = BeautifulSoup(content_html, "html.parser")
    node = soup.find(attrs={"data-id": data_id})
    return node.get("id") if node else None


def _create_or_replace_summary(graph: GraphClient, section_id: str, page_id: str | None,
                               title: str, body: str) -> tuple[str, str, bool]:
    """Create or update only the summary div. Returns page_id, web_url, created."""
    if page_id:
        try:
            content = graph.get_page_content(page_id)
            generated = _generated_id_for_data_id(content, "journal-summary")
            if generated:
                graph.patch_json(
                    f"/me/onenote/pages/{page_id}/content",
                    [{"target": generated, "action": "replace", "content": body}],
                )
                return page_id, "", False
        except OneNoteError:
            # Mapping may refer to a page that the user deleted. Recreate below.
            pass
    page = graph.create_page_html(section_id, page_html(title, body))
    return page["id"], _web_url(page), True


def sync_to_onenote(*, trades: pd.DataFrame, markets: dict[str, pd.DataFrame], settings: dict,
                    cache_path: Path, sync_map_path: Path,
                    progress: Callable[[str], None] | None = None) -> SyncResult:
    progress = progress or (lambda _msg: None)
    if trades.empty:
        raise OneNoteError("There are no trades in the journal to export.")

    graph = GraphClient(settings["client_id"], settings.get("authority", ""), cache_path)
    progress("Signing in to Microsoft and locating the OneNote notebook...")
    notebook, notebook_created = _find_or_create_notebook(graph, settings["notebook_name"])
    sync_map = _load_sync_map(sync_map_path)
    sync_map["notebook"] = {"id": notebook["id"], "displayName": notebook.get("displayName"), "web_url": _web_url(notebook)}
    sync_map.setdefault("months", {})

    created_trade_pages = 0
    existing_trade_pages = 0
    updated_summaries = 0
    created_sections = 0
    created_groups = 0

    work = trades.copy()
    work["EntryDT"] = pd.to_datetime(work["EntryDT"])
    work["ExitDT"] = pd.to_datetime(work["ExitDT"])
    work["MonthKey"] = work["EntryDT"].dt.strftime("%Y-%m")
    work["DayKey"] = work["EntryDT"].dt.strftime("%Y-%m-%d")

    for month_key, month_df in work.groupby("MonthKey", sort=True):
        first_ts = pd.Timestamp(month_df["EntryDT"].min())
        group_name = _safe_name(_month_name(first_ts))
        progress(f"Preparing {group_name}...")
        group, was_created = _find_or_create_group(graph, notebook["id"], group_name)
        created_groups += int(was_created)
        month_map = sync_map["months"].setdefault(month_key, {})
        month_map["section_group_id"] = group["id"]
        month_map["display_name"] = group_name
        month_map.setdefault("days", {})

        # Separate section for the monthly overview.
        monthly_section, sec_created = _find_or_create_section_in_group(graph, group["id"], "00 - Monthly Summary")
        created_sections += int(sec_created)
        month_map["summary_section_id"] = monthly_section["id"]

        month_page_links = {}

        # One section per trading day, then one page per trade.
        for day_key, day_df in month_df.groupby("DayKey", sort=True):
            day_ts = pd.Timestamp(day_df["EntryDT"].min())
            section_name = _safe_name(_day_section_name(day_ts))
            day_section, day_sec_created = _find_or_create_section_in_group(graph, group["id"], section_name)
            created_sections += int(day_sec_created)
            day_map = month_map["days"].setdefault(day_key, {})
            day_map["section_id"] = day_section["id"]
            day_map["display_name"] = section_name
            day_map.setdefault("trades", {})

            # Create-only trade pages. Never overwrite them, so OneNote ink remains safe.
            for _, trade in day_df.sort_values(["EntryDT", "ExitDT"]).iterrows():
                tid = str(trade["trade_id"])
                existing = day_map["trades"].get(tid)
                if existing and existing.get("page_id"):
                    existing_trade_pages += 1
                    if existing.get("web_url"):
                        month_page_links[tid] = existing["web_url"]
                    continue
                root = str(trade["Root"])
                market = markets.get(root)
                if market is None or market.empty:
                    progress(f"Skipping chart for {trade['Ativo']} {trade['EntryDT']:%d/%m %H:%M}; no {root} market data.")
                    continue
                progress(f"Creating OneNote page: {trade['EntryDT']:%d/%m} {_trade_page_title(trade)}")
                png = render_trade_chart_png(market, trade)
                html = page_html(_trade_page_title(trade), _trade_body(trade))
                page = graph.create_page_with_image(day_section["id"], html, png)
                page_info = {"page_id": page["id"], "web_url": _web_url(page), "title": _trade_page_title(trade)}
                day_map["trades"][tid] = page_info
                month_page_links[tid] = page_info["web_url"]
                created_trade_pages += 1
                _save_sync_map(sync_map_path, sync_map)

            # Daily summary updated on every sync. Trade pages themselves remain untouched.
            day_links = {
                tid: info.get("web_url", "")
                for tid, info in day_map["trades"].items()
                if info.get("web_url")
            }
            daily_title = f"Daily Summary - {day_ts:%d/%m/%Y}"
            daily_body = summary_body_html(day_df, daily_title, day_links)
            page_id, page_url, created = _create_or_replace_summary(
                graph, day_section["id"], day_map.get("summary_page_id"), daily_title, daily_body,
            )
            day_map["summary_page_id"] = page_id
            if page_url:
                day_map["summary_web_url"] = page_url
            updated_summaries += 1
            _save_sync_map(sync_map_path, sync_map)

        monthly_title = f"Monthly Summary - {group_name}"
        monthly_body = summary_body_html(month_df, monthly_title, month_page_links)
        page_id, page_url, created = _create_or_replace_summary(
            graph, monthly_section["id"], month_map.get("summary_page_id"), monthly_title, monthly_body,
        )
        month_map["summary_page_id"] = page_id
        if page_url:
            month_map["summary_web_url"] = page_url
        updated_summaries += 1
        _save_sync_map(sync_map_path, sync_map)

    progress("OneNote journal is up to date.")
    return SyncResult(
        notebook_name=settings["notebook_name"],
        created_trade_pages=created_trade_pages,
        existing_trade_pages=existing_trade_pages,
        updated_summary_pages=updated_summaries,
        created_sections=created_sections,
        created_month_groups=created_groups,
    )
