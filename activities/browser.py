"""Playwright browser activities with a declared step language for guarded RPA."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any, Literal

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, safe_path, validate_url
from app.domain.activity import Activity, ActivityContext, ActivityResult


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
    username: str = ""
    password: str = ""
    otp: str = ""
    screenshot_path: str = "page.png"
    screenshot_on_failure: bool = True
    timeout_ms: int = Field(default=30_000, ge=1, le=300_000)


class PlaywrightRobotActivity(Activity[RobotInputs]):
    name = "playwright_robot"
    category = "Platform / Browser"
    description = (
        "Run a browser robot from a declarative step list (portal login, download, extract)."
    )
    input_model = RobotInputs
    sensitive_fields = ("password", "otp")
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: RobotInputs) -> ActivityResult:
        start = inputs.start_url or inputs.base_url
        if start:
            validate_url(start)
        if inputs.base_url:
            validate_url(inputs.base_url)
        logs: list[str] = []
        extracted: dict[str, Any] = {}
        with sync_playwright() as playwright:
            browser = _launch(playwright, inputs.browser, inputs.headless)
            context = browser.new_context(ignore_https_errors=False, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(inputs.timeout_ms)
            try:
                if start:
                    page.goto(start, wait_until="domcontentloaded")
                    logs.append(f"goto {start}")
                if inputs.username:
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
                context.close()
                browser.close()

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


__all__ = ["Path", "PlaywrightRobotActivity", "PlaywrightScriptActivity"]
