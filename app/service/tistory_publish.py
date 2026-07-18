from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any

from playwright.async_api import Frame, Locator, Page, TimeoutError as PlaywrightTimeoutError, async_playwright


TITLE_SELECTORS = [
    "[contenteditable='true'][placeholder*='제목']",
    "textarea[placeholder*='제목']",
    "input[placeholder*='제목']",
    "#post-title-field",
]

EDITOR_IFRAME_SELECTORS = [
    "#editor-root iframe",
    "iframe[title*='에디터']",
    "iframe[title*='editor']",
    "iframe",
]

EDITOR_BODY_SELECTORS = [
    "body#tinymce",
    "body.mce-content-body",
    "body[contenteditable='true']",
    "body",
]

IMAGE_BUTTON_SELECTORS = [
    "button:has-text('이미지')",
    "button:has-text('사진')",
    "[aria-label*='이미지']",
    "[aria-label*='사진']",
    "[data-command='image']",
]

DONE_BUTTON_SELECTORS = [
    "button:has-text('완료')",
    "button:has-text('다음')",
]

FINAL_PUBLISH_BUTTON_SELECTORS = [
    "button:has-text('공개 발행')",
    "button:has-text('발행')",
    "button:has-text('Publish')",
]

MANAGE_PATH_CANDIDATES = [
    "/manage/post",
    "/manage/newpost",
]

IMAGE_PROMPT_PATTERN = re.compile(r"^\[여기에 들어갈 이미지 생성 프롬프트:\s*(.+?)\]\s*$")
LOGIN_ID_SELECTORS = [
    "input[name='loginId']",
    "input[name='email']",
    "input[type='email']",
    "input[name='loginKey']",
    "#loginId--1",
]
LOGIN_PASSWORD_SELECTORS = [
    "input[name='password']",
    "input[type='password']",
    "#password--2",
]
LOGIN_BUTTON_SELECTORS = [
    "button:has-text('로그인')",
    "button[type='submit']",
    "input[type='submit']",
]

POST_URL_PATTERN = re.compile(r"^https?://[^/]+\.tistory\.com/\d+")


def _strtobool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_blog_url(blog_url: str) -> str:
    normalized = blog_url.strip().rstrip("/")
    if not normalized:
        raise RuntimeError("티스토리 블로그 주소가 비어 있습니다.")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return normalized


def _normalize_editor_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _expected_body_text(body_markdown: str) -> str:
    lines: list[str] = []
    for raw_line in body_markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped or IMAGE_PROMPT_PATTERN.match(stripped):
            continue
        if stripped.startswith("### "):
            stripped = stripped[4:].strip()
        elif stripped.startswith("## "):
            stripped = stripped[3:].strip()
        elif stripped.startswith("# "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped:
            lines.append(stripped)
    return _normalize_editor_text(" ".join(lines))


def _extract_title(markdown: str, fallback_title: str) -> tuple[str, str]:
    lines = markdown.splitlines()
    title = fallback_title.strip()
    body_lines = lines[:]

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if line.startswith("# "):
            extracted = line[2:].strip()
            if extracted:
                title = extracted
            body_lines = lines[:index] + lines[index + 1 :]
            break

    if not title:
        raise RuntimeError("업로드할 제목을 찾지 못했습니다.")

    return title, "\n".join(body_lines).strip()


def _markdown_body_to_html(body_markdown: str) -> str:
    lines = body_markdown.splitlines()
    chunks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    slot_index = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            chunks.append(f"<p>{'<br>'.join(paragraph)}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            items_html = "".join(f"<li>{item}</li>" for item in list_items)
            chunks.append(f"<ul>{items_html}</ul>")
            list_items = []

    for raw_line in lines:
        stripped = raw_line.strip()

        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        image_match = IMAGE_PROMPT_PATTERN.match(stripped)
        if image_match:
            flush_paragraph()
            flush_list()
            slot_index += 1
            chunks.append(
                "<p>"
                f"<span data-wikitrend-image-slot=\"{slot_index}\">"
                f"__WIKITRENDBOT_IMAGE_SLOT_{slot_index}__"
                "</span>"
                "</p>"
            )
            continue

        escaped = html.escape(stripped)

        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            chunks.append(f"<h3>{html.escape(stripped[4:].strip())}</h3>")
            continue

        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            chunks.append(f"<h2>{html.escape(stripped[3:].strip())}</h2>")
            continue

        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            chunks.append(f"<h1>{html.escape(stripped[2:].strip())}</h1>")
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            list_items.append(html.escape(stripped[2:].strip()))
            continue

        flush_list()
        paragraph.append(escaped)

    flush_paragraph()
    flush_list()

    return "".join(chunks)


async def _locator_from_selectors(target: Page | Frame, selectors: list[str], timeout_ms: int = 1500) -> Locator | None:
    for selector in selectors:
        locator = target.locator(selector).first
        try:
            await locator.wait_for(state="attached", timeout=timeout_ms)
            return locator
        except PlaywrightTimeoutError:
            continue
    return None


async def _get_editor_frame(page: Page) -> Frame:
    for selector in EDITOR_IFRAME_SELECTORS:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="attached", timeout=4000)
        except PlaywrightTimeoutError:
            continue
        frame = await locator.content_frame()
        if frame is not None:
            return frame
    raise RuntimeError("티스토리 에디터 iframe을 찾지 못했습니다.")


async def _get_editor_body(frame: Frame) -> Locator:
    locator = await _locator_from_selectors(frame, EDITOR_BODY_SELECTORS, timeout_ms=4000)
    if locator is None:
        raise RuntimeError("티스토리 에디터 본문 영역을 찾지 못했습니다.")
    return locator


async def _open_editor(page: Page, blog_url: str) -> None:
    last_error: Exception | None = None
    for path in MANAGE_PATH_CANDIDATES:
        try:
            await page.goto(f"{blog_url}{path}", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=10000)
            await _get_editor_frame(page)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise RuntimeError(f"글쓰기 페이지에 진입하지 못했습니다: {last_error}")


async def _ensure_logged_in(page: Page, blog_url: str) -> None:
    try:
        await _open_editor(page, blog_url)
        return
    except Exception:
        pass

    await page.goto("https://www.tistory.com/auth/login", wait_until="domcontentloaded", timeout=30000)
    await page.bring_to_front()

    login_id = (os.getenv("TISTORY_LOGIN_ID") or "").strip()
    login_password = (os.getenv("TISTORY_LOGIN_PASSWORD") or "").strip()

    if login_id and login_password:
        auto_login_succeeded = await _try_auto_login(page, login_id=login_id, login_password=login_password)
        if not auto_login_succeeded:
            await page.wait_for_function(
                "() => !window.location.href.includes('/auth/login')",
                timeout=300000,
            )
    else:
        await page.wait_for_function(
            "() => !window.location.href.includes('/auth/login')",
            timeout=300000,
        )
    await _open_editor(page, blog_url)


async def _try_auto_login(page: Page, *, login_id: str, login_password: str) -> bool:
    id_input = await _locator_from_selectors(page, LOGIN_ID_SELECTORS, timeout_ms=4000)
    password_input = await _locator_from_selectors(page, LOGIN_PASSWORD_SELECTORS, timeout_ms=4000)
    login_button = await _locator_from_selectors(page, LOGIN_BUTTON_SELECTORS, timeout_ms=4000)

    if id_input is None or password_input is None or login_button is None:
        return False

    try:
        await id_input.click()
        await id_input.fill(login_id)
        await password_input.click()
        await password_input.fill(login_password)
        await login_button.click()
        await page.wait_for_function(
            "() => !window.location.href.includes('/auth/login')",
            timeout=20000,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


async def _dismiss_editor_popups(page: Page) -> None:
    popup_selectors = [
        "button:has-text('취소')",
        "button:has-text('닫기')",
        "button:has-text('나중에')",
    ]
    for selector in popup_selectors:
        locator = page.locator(selector).first
        try:
            if await locator.is_visible(timeout=500):
                await locator.click(timeout=1000)
        except Exception:  # noqa: BLE001
            continue


async def _fill_title(page: Page, title: str) -> None:
    title_locator = await _locator_from_selectors(page, TITLE_SELECTORS, timeout_ms=4000)
    if title_locator is None:
        role_locator = page.get_by_role("textbox", name="제목을 입력하세요")
        try:
            await role_locator.wait_for(state="attached", timeout=4000)
            title_locator = role_locator
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("제목 입력창을 찾지 못했습니다.") from exc

    await title_locator.click()
    try:
        await title_locator.fill(title)
    except Exception:
        await title_locator.evaluate(
            "(node, value) => { node.textContent = value; node.dispatchEvent(new Event('input', { bubbles: true })); }",
            title,
        )


async def _read_locator_text(locator: Locator) -> str:
    try:
        return await locator.input_value(timeout=1000)
    except Exception:  # noqa: BLE001
        pass

    try:
        return await locator.inner_text(timeout=1000)
    except Exception:  # noqa: BLE001
        return await locator.evaluate("(node) => node.textContent || ''")


async def _verify_title(page: Page, expected_title: str) -> dict[str, Any]:
    title_locator = await _locator_from_selectors(page, TITLE_SELECTORS, timeout_ms=2000)
    if title_locator is None:
        raise RuntimeError("검증할 제목 입력창을 찾지 못했습니다.")

    actual = _normalize_editor_text(await _read_locator_text(title_locator))
    expected = _normalize_editor_text(expected_title)
    if actual != expected:
        raise RuntimeError("티스토리 제목 입력값이 생성된 제목과 일치하지 않아 발행을 중단했습니다.")

    return {"title_matches": True, "title_length": len(actual)}


async def _set_editor_html(frame: Frame, html_content: str) -> None:
    body = await _get_editor_body(frame)
    await body.click()
    await frame.evaluate(
        """
        (html) => {
          if (window.tinymce && window.tinymce.activeEditor) {
            window.tinymce.activeEditor.setContent(html);
            window.tinymce.activeEditor.fire('change');
            return;
          }

          const target = document.body;
          target.innerHTML = html;
          target.dispatchEvent(new InputEvent('input', { bubbles: true }));
          target.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        html_content,
    )


async def _verify_body(frame: Frame, expected_body_markdown: str) -> dict[str, Any]:
    body = await _get_editor_body(frame)
    actual = _normalize_editor_text(await _read_locator_text(body))
    expected = _expected_body_text(expected_body_markdown)
    if not expected:
        raise RuntimeError("검증할 본문 텍스트가 비어 있습니다.")

    first_anchor = expected[: min(80, len(expected))]
    length_ratio = len(actual) / max(len(expected), 1)
    if first_anchor and first_anchor not in actual:
        raise RuntimeError("티스토리 본문에 생성된 글의 시작 문장이 확인되지 않아 발행을 중단했습니다.")
    if length_ratio < 0.7:
        raise RuntimeError("티스토리 본문 길이가 생성된 글보다 지나치게 짧아 발행을 중단했습니다.")

    remaining_slots = await frame.locator("[data-wikitrend-image-slot]").count()
    remaining_markers = await frame.locator("text=__WIKITRENDBOT_IMAGE_SLOT_").count()
    if remaining_slots or remaining_markers:
        raise RuntimeError("본문에 이미지 자리표시자가 남아 있어 발행을 중단했습니다.")

    return {
        "body_verified": True,
        "actual_length": len(actual),
        "expected_length": len(expected),
        "length_ratio": round(length_ratio, 3),
    }


async def _place_cursor_on_slot(frame: Frame, slot: int) -> None:
    found = await frame.evaluate(
        """
        (slot) => {
          const marker = document.querySelector(`[data-wikitrend-image-slot="${slot}"]`);
          if (!marker) return false;
          marker.scrollIntoView({ block: 'center' });
          const range = document.createRange();
          range.selectNodeContents(marker);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          return true;
        }
        """,
        slot,
    )
    if not found:
        raise RuntimeError(f"이미지 슬롯 {slot} 위치를 찾지 못했습니다.")


async def _upload_image(page: Page, frame: Frame, slot: int, image_path: Path) -> None:
    await _place_cursor_on_slot(frame, slot)
    existing_image_count = await frame.locator("img").count()

    button = await _locator_from_selectors(page, IMAGE_BUTTON_SELECTORS, timeout_ms=1500)
    if button is not None:
        try:
            await button.click(timeout=2000)
        except Exception:  # noqa: BLE001
            pass

    file_input = page.locator("input[type='file']").last
    try:
        await file_input.set_input_files(str(image_path), timeout=10000)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"이미지 업로드 입력창을 찾지 못했습니다: 슬롯 {slot}") from exc

    await frame.wait_for_function(
        """
        (expectedCount) => document.querySelectorAll('img').length >= expectedCount
        """,
        existing_image_count + 1,
        timeout=60000,
    )
    await frame.evaluate(
        """
        (slot) => {
          const marker = document.querySelector(`[data-wikitrend-image-slot="${slot}"]`);
          if (marker) {
            const parent = marker.closest('p');
            if (parent && parent.textContent && parent.textContent.includes('__WIKITRENDBOT_IMAGE_SLOT_')) {
              parent.remove();
              return;
            }
            marker.remove();
          }
        }
        """,
        slot,
    )


async def _click_first(page: Page, selectors: list[str], timeout_ms: int = 4000) -> bool:
    locator = await _locator_from_selectors(page, selectors, timeout_ms=timeout_ms)
    if locator is None:
        return False
    await locator.click(timeout=timeout_ms)
    return True


async def _wait_for_manual_publish(page: Page, timeout_seconds: int) -> str | None:
    deadline_ms = max(timeout_seconds, 1) * 1000
    try:
        await page.wait_for_function(
            """
            () => /^https?:\\/\\/[^/]+\\.tistory\\.com\\/\\d+/.test(window.location.href)
            """,
            timeout=deadline_ms,
        )
    except PlaywrightTimeoutError:
        return None
    return page.url


async def publish_to_tistory(
    *,
    blog_url: str,
    article_markdown: str,
    title: str,
    tags: list[str],
    image_paths_by_slot: dict[int, Path],
) -> dict[str, Any]:
    normalized_blog_url = _normalize_blog_url(blog_url)
    publish_title, body_markdown = _extract_title(article_markdown, title)
    html_content = _markdown_body_to_html(body_markdown)

    storage_state_path = Path(os.getenv("TISTORY_STORAGE_STATE_PATH", ".tistory-auth.json")).resolve()
    headless = _strtobool(os.getenv("TISTORY_HEADLESS"), default=False)
    keep_open = _strtobool(os.getenv("TISTORY_KEEP_BROWSER_OPEN"), default=False)
    auto_final_publish = _strtobool(os.getenv("TISTORY_AUTO_FINAL_PUBLISH"), default=False)
    manual_timeout_seconds = int(os.getenv("TISTORY_MANUAL_PUBLISH_TIMEOUT_SECONDS", "1800"))
    status_steps: list[dict[str, Any]] = []

    def add_step(step: str, message: str, **metadata: Any) -> None:
        status_steps.append({"step": step, "message": message, **metadata})

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1440, "height": 1000},
            "locale": "ko-KR",
        }
        if storage_state_path.exists():
            context_kwargs["storage_state"] = str(storage_state_path)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        try:
            add_step("LOGIN", "티스토리 로그인 상태를 확인했습니다.")
            await _ensure_logged_in(page, normalized_blog_url)
            add_step("EDITOR", "티스토리 글쓰기 화면에 진입했습니다.")
            await _dismiss_editor_popups(page)
            await _fill_title(page, publish_title)
            add_step("TITLE", "제목 입력을 완료했습니다.")
            title_verification = await _verify_title(page, publish_title)
            add_step("VERIFY_TITLE", "제목 입력값 검증을 완료했습니다.", **title_verification)

            frame = await _get_editor_frame(page)
            await _set_editor_html(frame, html_content)
            add_step("CONTENT", "본문 입력을 완료했습니다.")

            for slot, image_path in sorted(image_paths_by_slot.items()):
                await _upload_image(page, frame, slot, image_path)
                add_step("IMAGE", f"이미지 슬롯 {slot} 업로드를 완료했습니다.", slot=slot)

            body_verification = await _verify_body(frame, body_markdown)
            add_step("VERIFY_BODY", "본문 입력값 검증을 완료했습니다.", **body_verification)

            if tags:
                tag_input = page.locator("input[placeholder*='태그'], input[placeholder*='tag']").first
                try:
                    if await tag_input.is_visible(timeout=1000):
                        await tag_input.fill(", ".join(tags))
                        add_step("TAGS", "태그 입력을 완료했습니다.", tag_count=len(tags))
                    else:
                        raise PlaywrightTimeoutError("tag input not visible")
                except Exception:  # noqa: BLE001
                    add_step("TAGS_SKIPPED", "태그 입력창을 찾지 못해 태그 입력을 건너뛰었습니다.", tag_count=len(tags))
                    pass

            done_clicked = await _click_first(page, DONE_BUTTON_SELECTORS, timeout_ms=5000)
            if not done_clicked:
                raise RuntimeError("발행 전 완료 버튼을 찾지 못했습니다.")
            add_step("PUBLISH_DIALOG", "발행 설정 화면까지 열었습니다.")

            await page.wait_for_timeout(1200)
            if auto_final_publish:
                final_clicked = await _click_first(page, FINAL_PUBLISH_BUTTON_SELECTORS, timeout_ms=5000)
                if not final_clicked:
                    raise RuntimeError("최종 발행 버튼을 찾지 못했습니다.")
                add_step("FINAL_PUBLISH", "최종 발행 버튼을 클릭했습니다.")

                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except PlaywrightTimeoutError:
                    pass
            else:
                add_step(
                    "WAITING_FINAL_APPROVAL",
                    "자동 최종 발행이 꺼져 있어 브라우저에서 직접 발행 버튼을 눌러야 합니다.",
                    timeout_seconds=manual_timeout_seconds,
                )
                manual_post_url = await _wait_for_manual_publish(page, manual_timeout_seconds)
                if manual_post_url is None:
                    await context.storage_state(path=str(storage_state_path))
                    return {
                        "post_url": page.url,
                        "title": publish_title,
                        "uploaded_image_slots": sorted(image_paths_by_slot.keys()),
                        "tags": tags,
                        "status": "WAITING_FINAL_APPROVAL",
                        "final_publish_clicked": False,
                        "status_steps": status_steps,
                    }
                add_step("MANUAL_PUBLISHED", "브라우저에서 수동 발행 완료 URL을 감지했습니다.")

            await context.storage_state(path=str(storage_state_path))
            post_url = page.url
            published = bool(POST_URL_PATTERN.match(post_url))
            add_step(
                "PUBLISHED" if published else "UNKNOWN_RESULT",
                "게시 완료 URL을 확인했습니다." if published else "게시 완료 여부를 URL만으로 확정하지 못했습니다.",
                post_url=post_url,
            )

            if keep_open:
                await page.wait_for_timeout(5000)

            return {
                "post_url": post_url,
                "title": publish_title,
                "uploaded_image_slots": sorted(image_paths_by_slot.keys()),
                "tags": tags,
                "status": "PUBLISHED" if published else "UNKNOWN_RESULT",
                "final_publish_clicked": auto_final_publish,
                "status_steps": status_steps,
            }
        finally:
            await context.close()
            await browser.close()
