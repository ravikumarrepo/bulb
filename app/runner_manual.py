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
    """Manual-assisted upload: Browser stays open, user manually uploads, script captures links"""
    try:
        from playwright.sync_api import sync_playwright
        cfg=dict(state.config)
        print("\n" + "="*70)
        print("MANUAL-ASSISTED MODE")
        print("="*70)
        print("The browser will open and stay visible.")
        print("YOU will manually upload each file.")
        print("The script will automatically capture the link once it appears.")
        print("="*70 + "\n")

        with sync_playwright() as p:
            browser=p.chromium.launch(headless=False, slow_mo=500)
            context=browser.new_context(accept_downloads=True)
            try:
                for i,item in enumerate(list(state.items),1):
                    if state.stop_event.is_set():break
                    page=context.new_page()
                    update(item,status="Waiting for you",note="")
                    update(message=f"Opening browser for {item['filename']} ({i}/{len(state.items)}). YOU upload it manually.")

                    try:
                        page.goto(cfg["site_url"],wait_until="domcontentloaded",timeout=60000)
                        time.sleep(2)

                        print(f"\n{'='*70}")
                        print(f"FILE {i}/{len(state.items)}: {item['filename']}")
                        print(f"{'='*70}")
                        print(f"File location: {item['path']}")
                        print(f"\nINSTRUCTIONS:")
                        print(f"1. The browser is now open")
                        print(f"2. Click 'Choose File' or 'Browse'")
                        print(f"3. Navigate to: {item['path']}")
                        print(f"4. Select and upload the file")
                        print(f"5. Wait for the upload link to appear")
                        print(f"6. The script will automatically detect and capture it")
                        print(f"{'='*70}\n")

                        update(item,status="Ready - upload manually",note=f"Upload {item['filename']} through the browser")

                        deadline=time.time()+cfg["wait_seconds"]
                        found=""
                        expected=item["filename"].lower()

                        while time.time()<deadline and not state.stop_event.is_set():
                            # Look for the uploaded PDF link
                            selectors=[
                                'a[href$=".pdf"]',
                                'a[href*=".pdf?"]',
                                'a[href*=".pdf"]',
                                ".js-form-managed-file a[href]",
                                ".file-link a[href]",
                                'span[class*="file"] a[href]',
                            ]

                            if cfg.get("link_selector"):
                                selectors.insert(0, cfg["link_selector"])

                            seen=set()
                            for css in selectors:
                                try:
                                    loc=page.locator(css)
                                    count = loc.count()
                                    for n in range(min(count,100)):
                                        a=loc.nth(n)
                                        href=a.get_attribute("href") or ""
                                        if not href:
                                            continue
                                        try:
                                            absolute=page.evaluate("(u)=>new URL(u,location.href).href",href)
                                        except:
                                            absolute = href
                                        if absolute in seen:
                                            continue
                                        seen.add(absolute)
                                        basename=Path(urlparse(absolute).path).name.lower()
                                        label=(a.inner_text() or "").strip().lower()

                                        # More flexible matching
                                        matches_name=(
                                            basename==expected
                                            or basename.endswith("__"+expected)
                                            or expected in basename
                                            or label==expected
                                            or expected in label
                                        )

                                        if safe_link(absolute) and matches_name:
                                            found=absolute
                                            print(f"\n✓ LINK CAPTURED: {found}\n")
                                            break
                                    if found:
                                        break
                                except Exception:
                                    continue

                            if found:
                                break

                            time.sleep(1)

                        if found:
                            update(item,status="Captured",url=found,note="Link captured successfully")
                            update(message=f"✓ Captured {item['filename']}; moving to next file...")
                            print(f"✓ SUCCESS: Captured {item['filename']}")
                            time.sleep(2)
                            page.close()
                        elif state.stop_event.is_set():
                            update(item,status="Stopped",note="Stopped by user")
                            page.close()
                            break
                        else:
                            update(item,status="Timeout",note="No matching URL found within timeout period")
                            print(f"✗ TIMEOUT: No link found for {item['filename']}")
                            page.close()

                    except Exception as e:
                        update(item,status="Error",note=str(e)[:500])
                        print(f"✗ ERROR: {e}")
                        page.close()

                    time.sleep(1)
            finally:
                context.close()
                browser.close()
                print("\n" + "="*70)
                print("All files processed. Browser closed.")
                print("="*70 + "\n")
    except Exception as e:
        update(message=f"Automation error: {e}")
        print(f"FATAL ERROR: {e}")
    finally:
        with state.lock:
            state.running=False
            update(message="Queue finished.")
