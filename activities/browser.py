"""Playwright browser activities with a declared step language for guarded RPA.

Two activities live here:

* ``playwright_robot`` drives a portal from data: it can authenticate with an API token, a
  login form, or a login form followed by an email OTP. Browser state is kept per portal in a
  locked-down folder outside the run workspace, so a later run can reuse the session until
  the portal rejects it.
* ``playwright_script`` runs a team-written Playwright script with ``page``/``context``
  injected, for the long tail that cannot be expressed as steps.

All target URLs are validated before navigation and all generated files go through the run
workspace path guard.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import runpy
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, safe_path, validate_url
from activities.network import GraphReadMailActivity
from app.domain.activity import Activity, ActivityContext, ActivityResult

_FAILURE_WORDS = ("denied", "invalid", "expired", "not authorised", "not authorized")


class StepSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    selector: str = ""
    value: str = ""
    url: str = ""
    path: str = ""
    timeout_ms: int = Field(default=30_000, ge=1, le=300_000)


class RobotInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    base_url: str = ""
    start_url: str = ""
    steps: list[StepSpec] = Field(default_factory=list)

    # Authentication. ``none`` keeps the old behaviour: open ``start_url`` and optionally
    # autofill a username/password pair that is already on the page.
    operation: Literal["none", "api_token", "form", "form_otp"] = "none"
    portal: str = ""
    login_url: str = ""
    username: str = ""
    password: str = ""
    otp: str = ""
    api_token: str = ""
    api_token_header: str = "X-API-Token"

    username_selector: str = "input[name=username], #username, input[type=email]"
    password_selector: str = "input[name=password], #password, input[type=password]"
    submit_selector: str = "button[type=submit], #login"
    otp_selector: str = "input[name=otp], input[name=code], #otp, input[autocomplete=one-time-code]"
    otp_submit_selector: str = "button[type=submit], #verify"
    otp_resend_selector: str = ""

    # Reuse a saved session only when this URL still answers (otherwise log in again).
    session_check_url: str = ""
    state_file: str = ""

    # OTP retrieval through Microsoft Graph (the OTP mail is sent to a mailbox).
    otp_graph_base_url: str = "https://graph.microsoft.com/v1.0"
    otp_login_base_url: str = "https://login.microsoftonline.com"
    otp_tenant_id: str = ""
    otp_client_id: str = ""
    otp_client_secret: str = ""
    otp_mailbox: str = ""
    otp_sender: str = ""
    otp_regex: str = r"\b(\d{6})\b"
    otp_since: str = ""
    otp_timeout_seconds: float = Field(default=120, ge=0.1, le=900)
    otp_poll_seconds: float = Field(default=2, ge=0.05, le=60)
    otp_attempts: int = Field(default=2, ge=1, le=5)

    screenshot_path: str = "page.png"
    screenshot_on_failure: bool = True
    timeout_ms: int = Field(default=30_000, ge=1, le=300_000)


class PlaywrightRobotActivity(Activity[RobotInputs]):
    name = "playwright_robot"
    category = "Platform / Browser"
    description = (
        "Run a browser robot from a declarative step list, with API-token, form or "
        "form+email-OTP login and reusable per-portal sessions."
    )
    input_model = RobotInputs
    sensitive_fields = ("password", "otp", "api_token", "otp_client_secret")
    requires_admin_author = True

    operation_fields = {
        "none": ("start_url", "username", "password"),
        "api_token": ("start_url", "api_token", "api_token_header", "login_url"),
        "form": (
            "login_url",
            "username",
            "password",
            "username_selector",
            "password_selector",
            "submit_selector",
        ),
        "form_otp": (
            "login_url",
            "username",
            "password",
            "username_selector",
            "password_selector",
            "submit_selector",
            "otp_selector",
            "otp_submit_selector",
            "otp_resend_selector",
            "otp_graph_base_url",
            "otp_login_base_url",
            "otp_tenant_id",
            "otp_client_id",
            "otp_client_secret",
            "otp_mailbox",
            "otp_sender",
            "otp_regex",
            "otp_since",
            "otp_timeout_seconds",
            "otp_poll_seconds",
            "otp_attempts",
        ),
    }

    def run(self, ctx: ActivityContext, inputs: RobotInputs) -> ActivityResult:
        start = _absolute(inputs.base_url, inputs.start_url) if inputs.start_url else ""
        if start:
            validate_url(start)
        if inputs.base_url:
            validate_url(inputs.base_url)
        if inputs.operation == "api_token":
            _check_header(inputs.api_token_header, inputs.api_token)

        logs: list[str] = []
        extracted: dict[str, Any] = {}
        state_root = _state_root(ctx)
        state_name = _state_name(inputs)
        state_path = state_root / state_name
        lock_key = state_name.removesuffix(".json")
        extra_headers = (
            {inputs.api_token_header: inputs.api_token} if inputs.operation == "api_token" else {}
        )

        with sync_playwright() as playwright:
            browser = _launch(playwright, inputs.browser, inputs.headless)
            context: BrowserContext | None = None
            try:
                with _portal_lock(state_root, lock_key):
                    storage = state_path if state_path.is_file() else None
                    context = browser.new_context(
                        ignore_https_errors=False,
                        accept_downloads=True,
                        storage_state=str(storage) if storage else None,
                        extra_http_headers=extra_headers,
                    )
                    page = context.new_page()
                    page.set_default_timeout(inputs.timeout_ms)
                    if inputs.operation != "none":
                        reused = (
                            storage is not None
                            and inputs.operation != "api_token"
                            and _session_is_valid(context, inputs)
                        )
                        if reused:
                            logs.append("saved session reused")
                        else:
                            if storage is not None:
                                logs.append("saved session expired or rejected")
                            self._login(ctx, page, context, inputs, logs)
                            with contextlib.suppress(OSError):
                                context.storage_state(path=str(state_path))
                                state_path.chmod(0o600)
                            logs.append("session state saved")
                    if start:
                        page.goto(start, wait_until="domcontentloaded")
                        logs.append(f"goto {start}")
                    if inputs.operation == "none" and inputs.username:
                        self._maybe_autofill_credentials(page, inputs)
                    for index, step in enumerate(inputs.steps, start=1):
                        try:
                            value = self._execute(ctx, page, step, inputs.base_url)
                        except Exception:
                            if inputs.screenshot_on_failure:
                                failure = safe_path(ctx, f"failure-{index}.png")
                                page.screenshot(path=str(failure), full_page=True)
                            raise
                        if value is not None:
                            extracted[f"{step.action}_{index}"] = value
                        logs.append(f"{index}. {step.action}")
                screenshot = safe_path(ctx, inputs.screenshot_path)
                page.screenshot(path=str(screenshot), full_page=True)
                return ActivityResult.done(
                    {"steps": len(inputs.steps), "extracted": extracted, "log": logs},
                    "browser robot completed",
                    [artifact_for(ctx, screenshot)],
                )
            finally:
                if context is not None:
                    context.close()
                browser.close()

    def _login(
        self,
        ctx: ActivityContext,
        page: Page,
        context: BrowserContext,
        inputs: RobotInputs,
        logs: list[str],
    ) -> None:
        if inputs.operation == "api_token":
            target = inputs.login_url or inputs.start_url or "/portal/api/report"
            url = _absolute(inputs.base_url, target)
            validate_url(url)
            response = context.request.get(url, headers={inputs.api_token_header: inputs.api_token})
            if response.status in {401, 403}:
                raise ValueError("API token was rejected by the portal")
            if not response.ok:
                raise ValueError(f"API token check returned HTTP {response.status}")
            logs.append("api token accepted")
            return

        if inputs.operation in {"form", "form_otp"}:
            url = _absolute(inputs.base_url, inputs.login_url or "/portal")
            validate_url(url)
            page.goto(url, wait_until="domcontentloaded")
            since = ""
            if inputs.operation == "form_otp":
                # T0 is recorded before credentials are submitted, so an OTP mail that
                # predates this login can never be mistaken for a fresh one.
                since = inputs.otp_since or _utc(ctx.clock.now())
            _fill_first(page, inputs.username_selector, inputs.username)
            _fill_first(page, inputs.password_selector, inputs.password)
            _click_first(page, inputs.submit_selector)
            _raise_for_login_failure(page)
            if inputs.operation == "form_otp":
                self._complete_otp(ctx, page, inputs, since, logs)
            logs.append(f"{inputs.operation} login completed")
            return
        raise ValueError(f"unsupported login style: {inputs.operation}")

    def _complete_otp(
        self,
        ctx: ActivityContext,
        page: Page,
        inputs: RobotInputs,
        since: str,
        logs: list[str],
    ) -> None:
        used: set[str] = set()
        code = self._obtain_otp(ctx, inputs, since, used)
        for attempt in range(1, inputs.otp_attempts + 1):
            _fill_first(page, inputs.otp_selector, code)
            _click_first(page, inputs.otp_submit_selector)
            if not _page_has_failure(page):
                logs.append("email OTP verified")
                return
            used.add(code)
            if attempt >= inputs.otp_attempts:
                raise ValueError(
                    "the portal rejected every fresh OTP; check the mailbox and OTP regex"
                )
            logs.append("portal rejected the OTP; waiting for a fresh code")
            if inputs.otp_resend_selector:
                _click_first(page, inputs.otp_resend_selector)
            since = _utc(ctx.clock.now())
            code = self._obtain_otp(ctx, inputs, since, used)

    def _obtain_otp(
        self,
        ctx: ActivityContext,
        inputs: RobotInputs,
        since: str,
        used: set[str],
    ) -> str:
        graph_ready = all(
            (
                inputs.otp_tenant_id,
                inputs.otp_client_id,
                inputs.otp_client_secret,
                inputs.otp_mailbox,
            )
        )
        if not graph_ready:
            if inputs.otp:
                return inputs.otp
            raise ValueError(
                "form_otp needs Graph tenant/client/secret/mailbox, or a static otp value"
            )
        try:
            re.compile(inputs.otp_regex)
        except re.error as exc:
            raise ValueError(f"otp_regex is not a valid regular expression: {exc}") from exc
        deadline = time.monotonic() + inputs.otp_timeout_seconds
        last_error = ""
        while True:
            result = GraphReadMailActivity().execute(
                ctx,
                {
                    "tenant_id": inputs.otp_tenant_id,
                    "client_id": inputs.otp_client_id,
                    "client_secret": inputs.otp_client_secret,
                    "mailbox": inputs.otp_mailbox,
                    "sender": inputs.otp_sender,
                    "since": since,
                    "top": 5,
                    "code_regex": inputs.otp_regex,
                    "graph_base_url": inputs.otp_graph_base_url,
                    "login_base_url": inputs.otp_login_base_url,
                },
            )
            if result.outcome.value == "done":
                code = str(result.outputs.get("code") or "")
                if code and code not in used:
                    return code
            else:
                last_error = result.message
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = f" (last error: {last_error})" if last_error else ""
                raise ValueError(f"no fresh OTP email was found after {since}{detail}")
            time.sleep(min(inputs.otp_poll_seconds, remaining))

    @staticmethod
    def _maybe_autofill_credentials(page: Page, inputs: RobotInputs) -> None:
        for selector in ("input[type=email]", "input[name=username]", "#username", "#user"):
            locator = page.locator(selector)
            if locator.count():
                locator.first.fill(inputs.username)
                break
        for selector in ("input[type=password]", "input[name=password]", "#password"):
            locator = page.locator(selector)
            if locator.count():
                locator.first.fill(inputs.password)
                break
        if inputs.otp:
            for selector in ("input[name=otp]", "#otp", "input[autocomplete=one-time-code]"):
                locator = page.locator(selector)
                if locator.count():
                    locator.first.fill(inputs.otp)
                    break

    @staticmethod
    def _execute(ctx: ActivityContext, page: Page, step: StepSpec, base_url: str) -> Any:
        action = step.action.lower()
        if action == "goto":
            target = step.url or step.value
            if base_url and not target.startswith(("http://", "https://")):
                target = base_url.rstrip("/") + "/" + target.lstrip("/")
            validate_url(target)
            page.goto(target, wait_until="domcontentloaded")
            return None
        if action in {"fill", "type"}:
            page.locator(step.selector).fill(step.value)
            return None
        if action == "click":
            page.locator(step.selector).click()
            return None
        if action == "press":
            page.locator(step.selector or "body").press(step.value)
            return None
        if action == "check":
            page.locator(step.selector).check()
            return None
        if action == "select":
            page.locator(step.selector).select_option(step.value)
            return None
        if action == "wait_for":
            page.locator(step.selector).wait_for(timeout=step.timeout_ms)
            return None
        if action in {"wait", "sleep"}:
            page.wait_for_timeout(float(step.value or "1") * 1000)
            return None
        if action in {"text", "extract_text"}:
            return page.locator(step.selector).inner_text()
        if action in {"attribute", "extract_attribute"}:
            return page.locator(step.selector).get_attribute(step.value)
        if action == "count":
            return page.locator(step.selector).count()
        if action == "screenshot":
            path = safe_path(ctx, step.path or "screenshot.png")
            page.screenshot(path=str(path), full_page=True)
            return str(path.relative_to(ctx.workspace))
        if action == "download":
            path = safe_path(ctx, step.path or "download.bin")
            with page.expect_download() as info:
                page.locator(step.selector).click()
            download = info.value
            download.save_as(str(path))
            return str(path.relative_to(ctx.workspace))
        if action == "eval":
            return page.evaluate(step.value)
        raise ValueError(f"unsupported browser action: {step.action}")


class ScriptInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_path: str = ""
    script: str = ""
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    start_url: str = ""
    output_path: str = "script-result.json"
    screenshot_path: str = "script.png"


class PlaywrightScriptActivity(Activity[ScriptInputs]):
    name = "playwright_script"
    category = "Platform / Browser"
    description = "Run an existing Playwright Python script with page/context injected."
    input_model = ScriptInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: ScriptInputs) -> ActivityResult:
        if inputs.start_url:
            validate_url(inputs.start_url)
        path = safe_path(ctx, inputs.script_path)
        if inputs.script:
            path = ctx.workspace / ".uaf-browser-script.py"
            path.write_text(inputs.script, encoding="utf-8")
        if not path.is_file():
            return ActivityResult.failed("Playwright script not found")
        with sync_playwright() as playwright:
            browser = _launch(playwright, inputs.browser, inputs.headless)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            try:
                if inputs.start_url:
                    page.goto(inputs.start_url, wait_until="domcontentloaded")
                globals_map: dict[str, Any] = {
                    "page": page,
                    "context": context,
                    "browser": browser,
                    "playwright": playwright,
                    "workspace": ctx.workspace,
                    "ctx": ctx,
                    "result": {},
                }
                runpy.run_path(str(path), init_globals=globals_map)
                result = globals_map.get("result", {})
                from activities._common import write_json

                output = safe_path(ctx, inputs.output_path)
                write_json(output, result)
                screenshot = safe_path(ctx, inputs.screenshot_path)
                page.screenshot(path=str(screenshot), full_page=True)
                return ActivityResult.done(
                    {"result": result if isinstance(result, dict) else {}},
                    "Playwright script completed",
                    [artifact_for(ctx, output), artifact_for(ctx, screenshot)],
                )
            finally:
                context.close()
                browser.close()


def _launch(playwright: Playwright, browser: str, headless: bool) -> Browser:
    if browser == "firefox":
        return playwright.firefox.launch(headless=headless)
    if browser == "webkit":
        return playwright.webkit.launch(headless=headless)
    return playwright.chromium.launch(headless=headless)


def _absolute(base_url: str, value: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    if not base_url:
        raise ValueError(f"a base_url is required for relative URL: {value}")
    return base_url.rstrip("/") + "/" + value.lstrip("/")


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_header(name: str, value: str) -> None:
    if not name or not re.fullmatch(r"[A-Za-z0-9-]+", name):
        raise ValueError(f"invalid API token header name: {name!r}")
    if not value:
        raise ValueError("api_token is required for the api_token login style")
    if "\r" in value or "\n" in value:
        raise ValueError("API token must not contain line breaks")


def _fill_first(page: Page, selector: str, value: str) -> None:
    locator = page.locator(selector)
    if locator.count() == 0:
        raise ValueError(f"login field not found: {selector}")
    locator.first.fill(value)


def _click_first(page: Page, selector: str) -> None:
    locator = page.locator(selector)
    if locator.count() == 0:
        raise ValueError(f"login control not found: {selector}")
    locator.first.click()


def _page_has_failure(page: Page) -> bool:
    body = page.locator("body").inner_text().lower()
    return any(word in body for word in _FAILURE_WORDS)


def _raise_for_login_failure(page: Page) -> None:
    if _page_has_failure(page):
        raise ValueError("portal rejected the login form")


def _session_is_valid(context: BrowserContext, inputs: RobotInputs) -> bool:
    if not inputs.session_check_url:
        return True
    url = _absolute(inputs.base_url, inputs.session_check_url)
    validate_url(url)
    response = context.request.get(url)
    return response.ok


def _state_root(ctx: ActivityContext) -> Path:
    settings = getattr(ctx, "settings", None)
    data = getattr(settings, "data", None)
    root = getattr(data, "playwright_state", None)
    path = Path(root) if root else Path(tempfile.gettempdir()) / "uaf-playwright-state"
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(0o700)
    return path


def _state_name(inputs: RobotInputs) -> str:
    if inputs.state_file:
        name = inputs.state_file
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name):
            raise ValueError("state_file must be a simple file name")
        return name if name.endswith(".json") else f"{name}.json"
    key = inputs.portal or urlsplit(inputs.base_url or inputs.start_url).netloc or "default"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + ".json"


@contextlib.contextmanager
def _portal_lock(root: Path, key: str) -> Iterator[None]:
    """Serialise logins for one portal across threads and worker processes.

    The registry lives in the state folder as an atomically created lock file. A lock older
    than five minutes is considered abandoned, so a killed worker cannot block the portal.
    """
    lock = root / f".{key}.lock"
    deadline = time.monotonic() + 60
    handle: int | None = None
    while handle is None:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 300:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for the portal login lock: {key}") from None
            time.sleep(0.05)
    try:
        os.write(handle, f"{os.getpid()} {time.time():.3f}\n".encode())
        yield
    finally:
        os.close(handle)
        lock.unlink(missing_ok=True)


__all__ = ["Path", "PlaywrightRobotActivity", "PlaywrightScriptActivity"]
