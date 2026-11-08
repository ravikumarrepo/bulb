import time
from pathlib import Path
from urllib.parse import urlparse
from . import state

def update(item=None,**kwargs):
    with state.lock:
        if item is not None:item.update(kwargs)
        else:state.message=kwargs.get("message","")

def safe_link(url):
    p=urlparse(url)
    return p.scheme in ("http","https") and bool(p.netloc)

def run_queue():
    """Fully automated upload with proper Drupal handling"""
    try:
        from playwright.sync_api import sync_playwright
        cfg=dict(state.config)

        with sync_playwright() as p:
            # Launch with more realistic browser profile
            browser=p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                ]
            )

            # Create context with realistic headers and user agent
            context=browser.new_context(
                accept_downloads=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                java_script_enabled=True,
            )

            try:
                for i,item in enumerate(list(state.items),1):
                    if state.stop_event.is_set():break
                    page=context.new_page()

                    # Enable console logging for debugging
                    page.on("console", lambda msg: print(f"BROWSER: {msg.text}"))
                    page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))

                    update(item,status="Opening",note="")
                    update(message=f"Processing {item['filename']} ({i}/{len(state.items)})")
                    print(f"\n{'='*70}")
                    print(f"Processing: {item['filename']}")
                    print(f"{'='*70}")

                    try:
                        # Navigate and wait for everything to load
                        print(f"Navigating to {cfg['site_url']}")
                        page.goto(cfg["site_url"], wait_until="load", timeout=60000)

                        # Wait for network to settle
                        print("Waiting for page to fully load...")
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(2)

                        # Find the file input
                        selector=cfg["file_selector"] or 'input[type="file"]'
                        print(f"Looking for file input: {selector}")
                        file_input=page.locator(selector).first
                        file_input.wait_for(state="attached", timeout=45000)
                        print(f"Found file input")

                        # Check if input is visible or hidden
                        is_visible = file_input.is_visible()
                        print(f"File input visible: {is_visible}")

                        update(item,status="Uploading",note="Setting file...")

                        # Set the file - this works even if input is hidden
                        print(f"Setting file: {item['path']}")
                        file_input.set_input_files(item["path"], timeout=30000)
                        print("File set successfully")

                        update(item,status="Uploading",note="Waiting for server response...")

                        # Wait for Drupal AJAX upload - look for specific indicators
                        print("Waiting for upload to complete...")

                        # Strategy 1: Wait for the "Remove" button to appear (indicates upload success)
                        remove_button_appeared = False
                        try:
                            print("Looking for 'Remove' button...")
                            page.wait_for_selector('button:has-text("Remove"), input[value="Remove"]', timeout=15000)
                            remove_button_appeared = True
                            print("✓ Remove button found - upload successful!")
                        except Exception as e:
                            print(f"Remove button not found: {e}")

                        # Strategy 2: Wait for file link to appear
                        if not remove_button_appeared:
                            print("Looking for PDF link...")
                            try:
                                page.wait_for_selector('a[href*=".pdf"]', timeout=15000)
                                print("✓ PDF link appeared!")
                            except:
                                print("PDF link not immediately visible")

                        # Extra wait for DOM updates
                        time.sleep(3)

                        # Now search for the uploaded file link
                        print("Searching for uploaded file link...")
                        deadline=time.time()+cfg["wait_seconds"]
                        found=""
                        expected=item["filename"].lower()

                        attempt = 0
                        while time.time()<deadline and not state.stop_event.is_set():
                            attempt += 1
                            if attempt % 10 == 1:
                                print(f"Search attempt {attempt}...")

                            selectors=[
                                'a[href*=".pdf"]',
                                'a[href$=".pdf"]',
                                ".file-link a",
                                ".js-form-managed-file a",
                                'span.file a',
                            ]

                            if cfg.get("link_selector"):
                                selectors.insert(0, cfg["link_selector"])

                            seen=set()
                            for css in selectors:
                                try:
                                    loc=page.locator(css)
                                    count = loc.count()

                                    if count > 0 and attempt == 1:
                                        print(f"  Found {count} links matching '{css}'")

                                    for n in range(min(count,100)):
                                        a=loc.nth(n)
                                        href=a.get_attribute("href")
                                        if not href:
                                            continue

                                        # Get absolute URL
                                        try:
                                            absolute=page.evaluate("(u)=>new URL(u,location.href).href", href)
                                        except:
                                            absolute = href

                                        if absolute in seen:
                                            continue
                                        seen.add(absolute)

                                        # Extract filename from URL
                                        basename=Path(urlparse(absolute).path).name.lower()
                                        label=(a.inner_text() or "").strip().lower()

                                        # Flexible matching - check if expected filename is in the URL
                                        matches_name=(
                                            basename == expected or
                                            expected in basename or
                                            basename.endswith(expected) or
                                            label == expected or
                                            expected in label
                                        )

                                        if attempt == 1:
                                            print(f"    Link: {basename} | Label: {label} | Match: {matches_name}")

                                        if safe_link(absolute) and matches_name:
                                            found=absolute
                                            print(f"\n✓✓✓ MATCH FOUND ✓✓✓")
                                            print(f"URL: {found}")
                                            break

                                    if found:
                                        break
                                except Exception as e:
                                    if attempt == 1:
                                        print(f"  Error with selector '{css}': {e}")
                                    continue

                            if found:
                                break

                            time.sleep(1)

                        if found:
                            update(item,status="Captured",url=found,note="Successfully captured link")
                            update(message=f"✓ Captured {item['filename']}")
                            print(f"\n✓ SUCCESS: {item['filename']}")
                            print(f"URL: {found}\n")
                            page.close()
                        elif state.stop_event.is_set():
                            update(item,status="Stopped",note="Stopped by user")
                            page.close()
                            break
                        else:
                            # Take screenshot for debugging
                            screenshot_path = Path(item["path"]).parent / f"debug_{item['filename']}.png"
                            page.screenshot(path=str(screenshot_path))
                            print(f"\n✗ NO MATCH FOUND - Screenshot saved: {screenshot_path}")

                            # Dump page HTML for debugging
                            html_path = Path(item["path"]).parent / f"debug_{item['filename']}.html"
                            html = page.content()
                            with open(html_path, 'w', encoding='utf-8') as f:
                                f.write(html)
                            print(f"HTML saved: {html_path}")

                            update(item,status="Not found",note="No matching URL. See console for screenshot/HTML")
                            update(message=f"No link found for {item['filename']} - check debug files")

                            # Keep browser open for inspection
                            print("\nBrowser will stay open for 30 seconds for inspection...")
                            time.sleep(30)
                            page.close()

                    except Exception as e:
                        print(f"\n✗ ERROR: {str(e)}")
                        update(item,status="Error",note=str(e)[:500])

                        # Screenshot on error
                        try:
                            screenshot_path = Path(item["path"]).parent / f"error_{item['filename']}.png"
                            page.screenshot(path=str(screenshot_path))
                            print(f"Error screenshot saved: {screenshot_path}")
                        except:
                            pass

                        page.close()

                    time.sleep(1)

            finally:
                context.close()
                browser.close()

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        update(message=f"Fatal error: {e}")
    finally:
        with state.lock:
            state.running=False
            if not state.message.startswith("Fatal"):
                update(message="Queue finished.")
