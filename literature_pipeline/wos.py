from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from .models import Paper
from .normalize import normalize_doi
from .sources import (
    SourceAuthenticationError,
    SourceAuthorizationError,
    SourceConnectionError,
    SourceRateLimitError,
    _json,
)


LOGGER = logging.getLogger(__name__)
LOGIN_MARKERS = ("your session expired", "access denied", "session has expired")
MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少可选的 Playwright。请运行 .\\scripts\\setup.ps1 -WithPlaywright；"
            "普通 WoS API 和手工导入模式不需要安装它。"
        ) from exc
    return sync_playwright


def _profile_path(config: dict[str, Any]) -> Path:
    root = Path(config["_project_root"])
    configured = config["wos"].get("profile_dir", "browser/wos_profile")
    path = Path(configured)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _launch(playwright: Any, config: dict[str, Any], headless: bool):
    profile = _profile_path(config)
    profile.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        channel=config["wos"].get("browser_channel", "chrome"),
        headless=headless,
        viewport={"width": 1440, "height": 960},
        locale="en-US",
    )


def initialize_login(config: dict[str, Any]) -> None:
    """Open a persistent Chrome profile for user-completed SSO/MFA login."""
    sync_playwright = _import_playwright()
    with sync_playwright() as playwright:
        context = _launch(playwright, config, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(config["wos"]["home_url"], wait_until="domcontentloaded", timeout=60_000)
        print("\n请在打开的 Chrome 窗口中手动完成 Web of Science/机构 SSO/MFA 登录。")
        print("登录后请进入 Web of Science Core Collection > Advanced Search。")
        print("请手动运行以下检索式，并完成人机验证（如出现）：")
        print(config["search"]["wos_query"])
        print("确认已经看到检索结果列表后，回到此窗口按 Enter 保存会话。")
        input()
        context.close()


def _page_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=15_000).casefold()
    except Exception:
        return ""


def _visible_password_input(page: Any) -> bool:
    passwords = page.locator('input[type="password"]')
    return any(passwords.nth(index).is_visible() for index in range(passwords.count()))


def _is_logged_out(page: Any) -> bool:
    url = page.url.casefold()
    text = _page_text(page)
    return (
        any(marker in url for marker in ("login", "signin", "shibboleth"))
        or any(marker in text for marker in LOGIN_MARKERS)
        or _visible_password_input(page)
    )


def _page_location(page: Any) -> str:
    match = re.match(r"https?://([^/]+)(/[^?#]*)?", page.url)
    if not match:
        return "unknown page"
    return f"{match.group(1)}{match.group(2) or '/'}"


def _log_control_diagnostics(page: Any) -> None:
    """Log control attributes without reading field values or browser storage."""
    controls = page.locator('textarea, input, [contenteditable="true"]').evaluate_all(
        """
        elements => elements.slice(0, 30).map(element => ({
          tag: element.tagName.toLowerCase(),
          type: element.getAttribute('type'),
          id: element.id || null,
          name: element.getAttribute('name'),
          placeholder: element.getAttribute('placeholder'),
          ariaLabel: element.getAttribute('aria-label'),
          dataTa: element.getAttribute('data-ta'),
          role: element.getAttribute('role'),
          visible: Boolean(element.offsetWidth || element.offsetHeight)
        }))
        """
    )
    LOGGER.warning(
        "WoS 页面控件诊断：location=%s title=%s controls=%s",
        _page_location(page),
        page.title(),
        json.dumps(controls, ensure_ascii=False),
    )


def _log_result_diagnostics(page: Any) -> None:
    data_ta = page.locator("[data-ta]").evaluate_all(
        """
        elements => elements.slice(0, 120).map(element => ({
          tag: element.tagName.toLowerCase(),
          dataTa: element.getAttribute('data-ta'),
          className: typeof element.className === 'string' ? element.className.slice(0, 120) : null,
          href: element.getAttribute('href')
        }))
        """
    )
    custom_tags = page.locator("*").evaluate_all(
        """
        elements => {
          const counts = {};
          for (const element of elements) {
            const tag = element.tagName.toLowerCase();
            if (tag.includes('-')) counts[tag] = (counts[tag] || 0) + 1;
          }
          return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 80);
        }
        """
    )
    history_links = page.locator("app-history-entries-list a").evaluate_all(
        """
        elements => elements.slice(0, 30).map(element => ({
          text: (element.innerText || '').trim().slice(0, 120),
          href: element.getAttribute('href'),
          dataTa: element.getAttribute('data-ta'),
          className: typeof element.className === 'string' ? element.className.slice(0, 120) : null
        }))
        """
    )
    captcha = page.locator("app-captcha-details")
    captcha_visible = captcha.count() > 0 and captcha.first.is_visible()
    LOGGER.warning(
        "WoS 结果页诊断：location=%s title=%s captchaVisible=%s dataTa=%s customTags=%s historyLinks=%s",
        _page_location(page),
        page.title(),
        captcha_visible,
        json.dumps(data_ta, ensure_ascii=False),
        json.dumps(custom_tags, ensure_ascii=False),
        json.dumps(history_links, ensure_ascii=False),
    )


def _goto_with_retry(page: Any, url: str, timeout: int, attempts: int) -> None:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                page.wait_for_timeout(1_500)
    raise RuntimeError(f"navigation failed after {attempts} attempts: {last_error}")


def _first_visible(page_or_card: Any, selectors: Iterable[str]):
    for selector in selectors:
        locator = page_or_card.locator(selector)
        if locator.count() and locator.first.is_visible():
            return locator.first
    return None


def _dismiss_cookie_consent(page: Any) -> None:
    close_preferences = _first_visible(
        page,
        ("#close-pc-btn-handler", 'button[aria-label="Close"]'),
    )
    if close_preferences is not None:
        close_preferences.click(timeout=5_000)
        page.wait_for_timeout(300)

    consent_button = _first_visible(
        page,
        (
            "#onetrust-reject-all-handler",
            'button:has-text("Reject All")',
            'button:has-text("Reject all")',
            "#onetrust-accept-btn-handler",
        ),
    )
    if consent_button is not None:
        consent_button.click(timeout=5_000)
        page.wait_for_timeout(500)


def _extract_doi(text: str) -> str:
    match = re.search(r"10\.\d{4,9}/[^\s<>\"]+", text, flags=re.I)
    return normalize_doi(match.group(0)) if match else ""


def _extract_wos_id(text: str) -> str:
    match = re.search(r"WOS:\d+", text, flags=re.I)
    return match.group(0).upper() if match else ""


def _wos_api_key(wos: dict[str, Any]) -> str:
    configured = str(wos.get("api_key_env") or "").strip()
    variable_names = [configured, "WEBOFSCIENCE_API_KEY", "WEBOFSCIENDE_API_KEY"]
    for variable_name in variable_names:
        if variable_name:
            value = os.getenv(variable_name, "").strip()
            if value:
                return value
    return ""


def _add_year_filter(query: str, start: str, end: str) -> str:
    if re.search(r"\bPY\s*=", query, flags=re.I):
        return query
    try:
        start_year = dt.date.fromisoformat(start).year
        end_year = dt.date.fromisoformat(end).year
    except ValueError:
        return query
    years = " OR ".join(str(year) for year in range(start_year, end_year + 1))
    return f"{query} AND PY=({years})"


def _starter_publication_date(source: dict[str, Any]) -> str:
    year = source.get("publishYear") or source.get("publish_year") or ""
    month = source.get("publishMonth") or source.get("publish_month") or ""
    if not year:
        return ""
    month_text = str(month).strip()
    month_number = 0
    if month_text.isdigit():
        month_number = int(month_text)
    elif month_text:
        month_number = MONTH_NUMBERS.get(month_text[:3].casefold(), 0)
    return f"{int(year):04d}-{month_number:02d}" if 1 <= month_number <= 12 else str(year)


def _starter_citation_count(citations: Any) -> int:
    values = []
    for item in citations if isinstance(citations, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            values.append(int(item.get("count") or 0))
        except (TypeError, ValueError):
            continue
    return max(values, default=0)


def _parse_starter_documents(items: list[dict[str, Any]]) -> list[Paper]:
    papers: list[Paper] = []
    for item in items:
        source = item.get("source") or {}
        names = item.get("names") or {}
        identifiers = item.get("identifiers") or {}
        keywords = item.get("keywords") or {}
        links = item.get("links") or {}
        authors = []
        for author in names.get("authors") or []:
            if not isinstance(author, dict):
                continue
            name = author.get("displayName") or author.get("wosStandard") or ""
            if name:
                authors.append(str(name).strip())
        document_types = item.get("types") or item.get("sourceTypes") or ["article"]
        if isinstance(document_types, str):
            document_types = [document_types]
        papers.append(
            Paper(
                title=str(item.get("title") or "").strip(),
                authors=authors,
                journal=str(source.get("sourceTitle") or source.get("source_title") or "").strip(),
                publication_date=_starter_publication_date(source),
                doi=normalize_doi(identifiers.get("doi")),
                wos_id=str(item.get("uid") or "").strip().upper(),
                url=str(links.get("record") or "").strip(),
                keywords=[
                    str(keyword).strip()
                    for keyword in (keywords.get("authorKeywords") or [])
                    if str(keyword).strip()
                ],
                document_type=str(document_types[0] if document_types else "article"),
                citation_count=_starter_citation_count(item.get("citations")),
                sources=["wos"],
                reading_depth="Metadata only",
                sci_status="Confirmed (Web of Science Core Collection; Starter API)",
            )
        )
    return [paper for paper in papers if paper.title]


def _search_wos_api(
    config: dict[str, Any], wos: dict[str, Any], api_key: str, start: str, end: str
) -> tuple[list[Paper], int]:
    api_type = str(wos.get("api_type", "starter")).casefold()
    if api_type != "starter":
        raise ValueError(f"unsupported wos.api_type={api_type}")
    query = _add_year_filter(config["search"]["wos_query"], start, end)
    limit = min(50, max(1, int(config["search"].get("candidate_pool_size", 30))))
    params: dict[str, Any] = {
        "q": query,
        "db": wos.get("database", "WOS"),
        "limit": limit,
        "page": 1,
        "sortField": wos.get("sort_field", "LD+D"),
    }
    if start and end and wos.get("use_modified_time_span", True):
        params["modifiedTimeSpan"] = f"{start}+{end}"
    endpoint = str(
        wos.get("api_url", "https://api.clarivate.com/apis/wos-starter/v1")
    ).rstrip("/")
    data = _json(
        endpoint + "/documents?" + urllib.parse.urlencode(params),
        headers={"Accept": "application/json", "X-ApiKey": api_key},
        timeout=int(config["search"].get("request_timeout_seconds", 30)),
    )
    items = data.get("hits") or []
    total = int((data.get("metadata") or {}).get("total") or len(items))
    return _parse_starter_documents(items), total


def _parse_result_cards(page: Any, selectors: dict[str, Any], max_results: int) -> list[Paper]:
    cards = None
    for selector in selectors["result_cards"]:
        candidate = page.locator(selector)
        if candidate.count():
            cards = candidate
            break
    if cards is None:
        _log_result_diagnostics(page)
        raise RuntimeError("WoS 结果页结构未识别；请在 config/sources.yaml 更新 selectors")

    papers: list[Paper] = []
    for index in range(min(cards.count(), max_results)):
        card = cards.nth(index)
        title_node = _first_visible(card, selectors["title"])
        if title_node is None:
            continue
        title = " ".join(title_node.inner_text().split())
        href = title_node.get_attribute("href") or ""
        text = card.inner_text()
        authors_node = _first_visible(card, selectors["authors"])
        source_node = _first_visible(card, selectors["source"])
        date_match = re.search(r"\b(19|20)\d{2}(?:-\d{2}-\d{2})?\b", text)
        authors_text = authors_node.inner_text() if authors_node else ""
        papers.append(
            Paper(
                title=title,
                authors=[part.strip() for part in re.split(r";|\band\b", authors_text) if part.strip()],
                journal=source_node.inner_text().strip() if source_node else "",
                publication_date=date_match.group(0) if date_match else "",
                doi=_extract_doi(text),
                wos_id=_extract_wos_id(text),
                url=href,
                sources=["wos"],
                reading_depth="Metadata only",
                sci_status="Confirmed (SCI-EXPANDED)",
            )
        )
    return papers


def search_wos(
    config: dict[str, Any], start: str = "", end: str = ""
) -> tuple[list[Paper], str]:
    """Search WoS using its API, a manual export inbox, or browser automation."""
    wos = config.get("wos") or {}
    if not wos.get("enabled", True):
        return [], "skipped: disabled"
    mode = wos.get("mode", "manual_import")
    if mode == "api":
        api_key = _wos_api_key(wos)
        if not api_key:
            return [], "skipped: missing WEBOFSCIENCE_API_KEY/WEBOFSCIENDE_API_KEY"
        try:
            papers, total = _search_wos_api(config, wos, api_key, start, end)
            return papers, f"ok: {len(papers)} WoS Core records (Starter API, {total} matched)"
        except SourceAuthenticationError:
            return [], "error: authentication failed; check WoS API Key activation"
        except SourceAuthorizationError:
            return [], "error: API key lacks Web of Science Starter access"
        except SourceRateLimitError:
            return [], "error: Web of Science Starter rate limit exceeded"
        except SourceConnectionError:
            return [], "error: Web of Science Starter connection failed after retries"
        except Exception as exc:
            LOGGER.warning("WoS API 检索失败：%s", exc)
            return [], f"error: WoS API {type(exc).__name__}"
    if mode == "manual_import":
        from .wos_import import scan_wos_inbox

        return scan_wos_inbox(config)
    if mode != "playwright":
        return [], f"unverified: unsupported wos.mode={mode}"
    selectors = wos["selectors"]
    try:
        sync_playwright = _import_playwright()
    except Exception as exc:
        return [], f"unverified: {exc}"
    with sync_playwright() as playwright:
        context = _launch(playwright, config, headless=bool(wos.get("headless", True)))
        try:
            page = context.new_page()
            timeout = int(wos.get("navigation_timeout_seconds", 90)) * 1_000
            attempts = int(wos.get("navigation_attempts", 2))
            _goto_with_retry(page, wos["home_url"], timeout, attempts)
            if _is_logged_out(page):
                return [], f"unverified: login/session required at {_page_location(page)}"
            _goto_with_retry(page, wos["advanced_search_url"], timeout, attempts)
            page.wait_for_timeout(int(wos.get("page_ready_wait_seconds", 8)) * 1_000)
            if _is_logged_out(page):
                return [], f"unverified: login/session required at {_page_location(page)}"

            query_box = _first_visible(page, selectors["query_input"])
            if query_box is None:
                _log_control_diagnostics(page)
                return [], "unverified: search input not found"
            _dismiss_cookie_consent(page)
            query_box.fill(config["search"]["wos_query"])
            search_button = _first_visible(page, selectors["search_button"])
            if search_button is None:
                return [], "unverified: search button not found"
            search_button.click()
            page.wait_for_timeout(int(wos.get("result_wait_seconds", 5)) * 1_000)
            captcha = page.locator("app-captcha-details")
            if captcha.count() > 0 and captcha.first.is_visible():
                return [], "unverified: CAPTCHA requires manual completion"

            papers = _parse_result_cards(
                page, selectors, int(config["search"]["candidate_pool_size"])
            )
            return papers, f"ok: {len(papers)} SCI-EXPANDED records"
        except Exception as exc:
            LOGGER.warning("WoS 自动检索失败：%s", exc)
            message = str(exc)
            if "ERR_NETWORK_ACCESS_DENIED" in message:
                return [], "unverified: network access denied"
            if "ERR_CONNECTION_CLOSED" in message:
                return [], "unverified: connection closed"
            if "Timeout" in type(exc).__name__ or "Timeout" in message:
                return [], "unverified: page timeout"
            return [], f"unverified: {type(exc).__name__}"
        finally:
            context.close()
