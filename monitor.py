#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

SOURCE_URL = "https://www.amway.com.vn/vn/promotions"
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "state.json"
NOTIFICATION_PATH = ROOT / "data" / "notification.md"
RESULT_PATH = ROOT / "data" / "last-run.json"
SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def deaccent(value: str) -> str:
    value = (value or "").replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")


def normalize_title(value: str) -> str:
    value = collapse_ws(deaccent(value)).lower()
    value = re.sub(r"[“”\"'’`]", "", value)
    value = re.sub(r"[^a-z0-9\s-]", " ", value)
    return collapse_ws(value)


def canonicalize_url(raw: str) -> str:
    if not raw:
        return ""
    try:
        absolute = urljoin(SOURCE_URL, raw)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            return ""
        if parsed.netloc.lower() != "www.amway.com.vn":
            return ""
        if re.search(r"\.pdf$", parsed.path, re.I):
            return ""
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))
    except Exception:
        return ""


def title_from_text(value: str) -> str:
    text = collapse_ws(html.unescape(value or ""))
    match = re.search(r"(?i)\bCTKM\s*[:：-]\s*\S", text)
    if not match:
        return ""
    candidate = text[match.start():]

    # The live cards often place the hotline/subtext immediately after the title.
    # Cut only on phrases known to be non-title metadata.
    stop_patterns = [
        r"\s+Mọi\s+thắc\s+mắc\b",
        r"\s+Moi\s+thac\s+mac\b",
        r"\s+Hotline\b",
        r"\s+Xem\s+chi\s+tiết\b",
        r"\s+Xem\s+chi\s+tiet\b",
        r"\s+Xem\s+tại\s+đây\b",
        r"\s+Xem\s+tai\s+day\b",
    ]
    for pattern in stop_patterns:
        cut = re.search(pattern, candidate, re.I)
        if cut:
            candidate = candidate[:cut.start()]

    candidate = collapse_ws(candidate).strip(" -|•")
    if len(candidate) < 8 or len(candidate) > 260:
        return ""
    return candidate


class PromotionHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, str]] = []
        self.anchor_buffers: list[dict[str, object]] = []
        self.text_chunks: list[tuple[str, str]] = []
        self.all_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = {str(k).lower(): str(v or "") for k, v in attrs}
        inherited_href = self.stack[-1]["href"] if self.stack else ""
        href = attrs_dict.get("href", "") if tag.lower() == "a" else inherited_href
        self.stack.append({"tag": tag.lower(), "href": href})
        if tag.lower() == "a":
            self.anchor_buffers.append({"depth": len(self.stack), "href": href, "parts": []})

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        text = collapse_ws(data)
        if not text:
            return
        self.all_text.append(text)
        current_href = self.stack[-1]["href"] if self.stack else ""
        self.text_chunks.append((text, current_href))
        for buf in self.anchor_buffers:
            if len(self.stack) >= int(buf["depth"]):
                parts = buf["parts"]
                assert isinstance(parts, list)
                parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        # HTML from real sites may be imperfect. Pop back to the matching tag.
        while self.stack:
            entry = self.stack.pop()
            if entry["tag"] == tag:
                break

    def close_and_collect_anchors(self) -> list[tuple[str, str]]:
        # Anchor buffers are useful even if HTMLParser saw imperfect closing tags.
        out: list[tuple[str, str]] = []
        for buf in self.anchor_buffers:
            parts = buf["parts"]
            assert isinstance(parts, list)
            out.append((collapse_ws(" ".join(parts)), str(buf["href"])))
        return out


def parse_promotions(rendered_html: str) -> list[dict[str, str]]:
    parser = PromotionHTMLParser()
    parser.feed(rendered_html)
    parser.close()

    full_text = collapse_ws(" ".join(parser.all_text))
    normalized_page = collapse_ws(deaccent(full_text)).lower()
    if "failed to load more products" in full_text.lower():
        raise RuntimeError("Amway reported: Failed to load more products")
    if "chuong trinh khuyen mai" not in normalized_page:
        raise RuntimeError("Không tìm thấy heading CHƯƠNG TRÌNH KHUYẾN MÃI")

    found: dict[str, dict[str, str]] = {}

    # Prefer anchors because they can carry a useful Amway detail URL.
    for anchor_text, href in parser.close_and_collect_anchors():
        title = title_from_text(anchor_text)
        if not title:
            continue
        key = normalize_title(title)
        if not key:
            continue
        found.setdefault(key, {"title": title, "detailUrl": canonicalize_url(href)})

    # Fallback to text nodes. The live Amway cards can render the title outside <a>.
    for text, href in parser.text_chunks:
        title = title_from_text(text)
        if not title:
            continue
        key = normalize_title(title)
        if not key:
            continue
        item = found.setdefault(key, {"title": title, "detailUrl": ""})
        if not item.get("detailUrl"):
            item["detailUrl"] = canonicalize_url(href)

    promotions = list(found.values())
    promotions.sort(key=lambda item: normalize_title(item["title"]))
    if not promotions:
        raise RuntimeError("Trang render thành công nhưng không đọc được card CTKM nào")
    return promotions


def chrome_binary() -> str:
    configured = os.environ.get("CHROME_BIN", "").strip()
    candidates = [
        configured,
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("Không tìm thấy Chrome/Chromium")


def render_page() -> str:
    chrome = chrome_binary()
    last_error = ""
    for attempt in range(1, 3):
        with tempfile.TemporaryDirectory(prefix="amway-monitor-") as profile:
            cmd = [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--window-size=1365,900",
                "--lang=vi-VN",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=15000",
                "--dump-dom",
                SOURCE_URL,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            except subprocess.TimeoutExpired:
                last_error = f"Chrome timeout (lần {attempt})"
                time.sleep(2)
                continue
            if proc.returncode != 0:
                last_error = collapse_ws(proc.stderr)[-800:] or f"Chrome exit {proc.returncode}"
                time.sleep(2)
                continue
            output = proc.stdout or ""
            if len(output) < 1000:
                last_error = f"HTML quá ngắn ({len(output)} bytes)"
                time.sleep(2)
                continue
            try:
                # Validation here prevents accepting an early/empty dynamic render.
                parse_promotions(output)
                return output
            except Exception as exc:
                last_error = str(exc)
                time.sleep(2)
                continue
    raise RuntimeError(f"Không lấy được snapshot hợp lệ từ Amway: {last_error}")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"schemaVersion": SCHEMA_VERSION, "initialized": False, "known": {}, "currentKeys": []}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"state.json không đọc được: {exc}") from exc
    if state.get("schemaVersion") != SCHEMA_VERSION:
        raise RuntimeError("state.json có schemaVersion không hỗ trợ")
    if not isinstance(state.get("known"), dict) or not isinstance(state.get("currentKeys"), list):
        raise RuntimeError("state.json sai cấu trúc")
    return state


def save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def reconcile(state: dict, promotions: list[dict[str, str]], timestamp: str) -> tuple[dict, list[dict[str, str]], bool]:
    known = dict(state.get("known", {}))
    current_keys: list[str] = []
    new_items: list[dict[str, str]] = []
    metadata_changed = False

    for item in promotions:
        key = normalize_title(item["title"])
        current_keys.append(key)
        if key not in known:
            known[key] = {
                "title": item["title"],
                "detailUrl": item.get("detailUrl", ""),
                "firstSeenAt": timestamp,
            }
            if state.get("initialized"):
                new_items.append(item)
            metadata_changed = True
        else:
            record = dict(known[key])
            # Same normalized title remains the same promotion for notification purposes.
            # URL changes are metadata updates, not NEW.
            if item.get("detailUrl") and item.get("detailUrl") != record.get("detailUrl"):
                record["detailUrl"] = item["detailUrl"]
                record["lastMetadataChangeAt"] = timestamp
                metadata_changed = True
            if item["title"] != record.get("title"):
                record["title"] = item["title"]
                record["lastMetadataChangeAt"] = timestamp
                metadata_changed = True
            known[key] = record

    current_keys = sorted(set(current_keys))
    previous_current = sorted(set(state.get("currentKeys", [])))
    current_changed = current_keys != previous_current

    next_state = dict(state)
    next_state.update({
        "schemaVersion": SCHEMA_VERSION,
        "initialized": True,
        "sourceUrl": SOURCE_URL,
        "known": known,
        "currentKeys": current_keys,
    })
    if not state.get("initialized"):
        next_state["baselineAt"] = timestamp
    if current_changed or metadata_changed or not state.get("initialized"):
        next_state["lastStateChangeAt"] = timestamp

    return next_state, new_items, (current_changed or metadata_changed or not state.get("initialized"))


def write_notification(new_items: list[dict[str, str]]) -> None:
    if NOTIFICATION_PATH.exists():
        NOTIFICATION_PATH.unlink()
    if not new_items:
        return
    count = len(new_items)
    body = (
        f"@${{GITHUB_REPOSITORY_OWNER}}\n\n"
        f"Amway vừa có **{count} chương trình khuyến mãi mới**.\n\n"
        f"Mở trang khuyến mãi: {SOURCE_URL}\n\n"
        "_Thông báo tự động bởi Amway Cloud Monitor._\n"
    )
    NOTIFICATION_PATH.write_text(body, encoding="utf-8")


def main() -> int:
    timestamp = now_iso()
    try:
        rendered = render_page()
        promotions = parse_promotions(rendered)
        state = load_state()
        next_state, new_items, state_changed = reconcile(state, promotions, timestamp)
        save_json(STATE_PATH, next_state)
        write_notification(new_items)
        save_json(RESULT_PATH, {
            "ok": True,
            "checkedAt": timestamp,
            "promotionCount": len(promotions),
            "newCount": len(new_items),
            "baselineCreated": not state.get("initialized"),
            "stateChanged": state_changed,
            "titles": [item["title"] for item in promotions],
        })
        print(f"OK: {len(promotions)} card, NEW={len(new_items)}, baseline={not state.get('initialized')}")
        for item in promotions:
            print(f"- {item['title']}")
        return 0
    except Exception as exc:
        if NOTIFICATION_PATH.exists():
            NOTIFICATION_PATH.unlink()
        save_json(RESULT_PATH, {"ok": False, "checkedAt": timestamp, "error": str(exc)})
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
