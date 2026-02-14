#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "playwright>=1.49.0",
#     "rich>=14.2.0",
#     "trafilatura>=2.0.0",
#     "typer>=0.20.1",
# ]
# ///

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from time import monotonic
from urllib.parse import urlparse

import typer
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
import trafilatura

APP = typer.Typer(add_completion=False)
CONSOLE = Console()

OutputFormat = Literal["csv", "html", "json", "markdown", "raw-html", "txt", "xml", "xmltei"]


def detect_browser_path() -> str | None:
    """Try common local browser paths to avoid Playwright download."""

    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Arc.app/Contents/MacOS/Arc",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/usr/bin/brave-browser",
        "/usr/bin/brave-browser-stable",
        "/snap/bin/chromium",
        "/snap/bin/brave",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def render_html(
    url: str,
    timeout_ms: int,
    browser_path: str | None,
    verbose: bool,
) -> str:
    """使用 Playwright 渲染页面并返回完整 HTML。"""

    if verbose:
        CONSOLE.print(
            f"[cyan]Launching browser[/cyan] "
            f"(strategy=domcontentloaded+load+stability, timeout_ms={timeout_ms})",
            highlight=False,
        )

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": True}
        if browser_path:
            launch_options["executable_path"] = browser_path
            if verbose:
                CONSOLE.print(
                    f"[cyan]Using browser path[/cyan] {browser_path}",
                    highlight=False,
                )
        elif verbose:
            CONSOLE.print("[cyan]Using Playwright-managed Chromium[/cyan]", highlight=False)

        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context()
        page = context.new_page()
        if verbose:
            CONSOLE.print(f"[cyan]Navigating[/cyan] {url}", highlight=False)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("load", timeout=min(timeout_ms, 5000))
            if verbose:
                CONSOLE.print("[cyan]Load event reached[/cyan]", highlight=False)
        except PlaywrightTimeoutError:
            if verbose:
                CONSOLE.print("[yellow]Load event wait timed out, continue[/yellow]", highlight=False)

        # Wait briefly for client-side rendering to settle without risking long hangs.
        deadline = monotonic() + 2.0
        previous_size: int | None = None
        stable_rounds = 0
        while monotonic() < deadline:
            current_size = page.evaluate(
                "() => document.body ? document.body.innerHTML.length : 0"
            )
            if previous_size is not None and abs(current_size - previous_size) <= 64:
                stable_rounds += 1
            else:
                stable_rounds = 0
            if stable_rounds >= 2:
                if verbose:
                    CONSOLE.print("[cyan]DOM stabilized[/cyan]", highlight=False)
                break
            previous_size = current_size
            page.wait_for_timeout(300)
        html = page.content()
        context.close()
        browser.close()

    if verbose:
        CONSOLE.print(f"[green]Rendered HTML size[/green] {len(html)} chars", highlight=False)

    return html


def extract_content(html: str, url: str, output_format: OutputFormat, verbose: bool) -> str:
    """使用 trafilatura 从 HTML 提取内容。"""
    if verbose:
        CONSOLE.print(f"[cyan]Extracting content[/cyan] as {output_format}", highlight=False)

    content = trafilatura.extract(
        html,
        url=url,
        output_format=output_format,
        include_formatting=True,
        include_links=True,
    )
    if not content:
        raise ValueError("Failed to extract main content from the rendered HTML.")

    if verbose:
        CONSOLE.print(f"[green]Extracted content size[/green] {len(content)} chars", highlight=False)

    return content


@APP.command()
def fetch(
    url: str = typer.Argument(..., help="Target URL to render into content."),
    output: Path | None = typer.Option(None, help="Write output to file instead of stdout."),
    timeout_ms: int = typer.Option(60000, help="Playwright navigation timeout in milliseconds."),
    browser_path: Path | None = typer.Option(
        None,
        help="Optional local Chromium-based browser path. Auto-detected if omitted.",
    ),
    output_format: OutputFormat = typer.Option(
        "markdown",
        help="Output format: csv, html, json, markdown, raw-html, txt, xml, xmltei.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Print progress and diagnostic logs."),
) -> None:
    """通过 Playwright 渲染并用 trafilatura 提取内容。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise typer.BadParameter("Only http or https URLs are supported.")

    resolved_browser_path = str(browser_path) if browser_path else detect_browser_path()
    try:
        html = render_html(
            url,
            timeout_ms=timeout_ms,
            browser_path=resolved_browser_path,
            verbose=verbose,
        )
        content = (
            html
            if output_format == "raw-html"
            else extract_content(html, url, output_format, verbose=verbose)
        )
    except PlaywrightTimeoutError as exc:
        CONSOLE.print(
            Panel.fit(
                f"[red]Playwright timeout[/red]\n{exc}",
                title="Request Failed",
            )
        )
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        CONSOLE.print(
            Panel.fit(
                f"[red]Extraction failed[/red]\n{exc}",
                title="Request Failed",
            )
        )
        raise typer.Exit(code=1) from exc
    except PlaywrightError as exc:
        hint = "Install Playwright browsers with: uv run playwright install chromium"
        CONSOLE.print(
            Panel.fit(
                f"[red]Playwright launch failed[/red]\\n{exc}\\n{hint}",
                title="Request Failed",
            )
        )
        raise typer.Exit(code=1) from exc

    if output:
        output.write_text(content, encoding="utf-8")
        CONSOLE.print(f"[green]Saved output to[/green] {output}", highlight=False)
    else:
        CONSOLE.print(content, markup=False)


if __name__ == "__main__":
    APP()
