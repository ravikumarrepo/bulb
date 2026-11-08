import time
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from . import state

def update(item=None,**kwargs):
    with state.lock:
        if item is not None:item.update(kwargs)
        else:state.message=kwargs.get("message","")

def safe_link(url):
    p=urlparse(url)
    return p.scheme in ("http","https") and bool(p.netloc)

def run_queue():
    try:
        from playwright.sync_api import sync_playwright
        cfg=dict(state.config)
        print("DEBUG upload_trigger:", repr(cfg.get("upload_trigger")))
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=False)
            context=browser.new_context(accept_downloads=True)
            try:
                for i,item in enumerate(list(state.items),1):
                    if state.stop_event.is_set():break
                    page=context.new_page()
                    update(item,status="Opening",note="")
                    update(message=f"Opening {cfg['site_url']} for {item['filename']} ({i}/{len(state.items)}).")
                    try:
                        page.goto(cfg["site_url"],wait_until="domcontentloaded",timeout=60000)

                        # Wait for page to fully load and Drupal to initialize
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(1)

                        selector=cfg["file_selector"] or 'input[type="file"]'
                        file_input=page.locator(selector).first
                        file_input.wait_for(state="attached",timeout=45000)

                        # Detect websites that automatically upload when a file is selected.
                        auto_upload = False
                        try:
                            once_attr = file_input.get_attribute("data-once") or ""
                            auto_upload = (
                                "auto-file-upload" in once_attr
                                or "webform-auto-file-upload" in once_attr
                            )
                            if auto_upload:
                                print(f"DEBUG: Auto-upload detected (data-once={once_attr})")
                        except Exception:
                            pass

                        # Set the file and wait for AJAX if auto-upload is detected
                        file_input.set_input_files(item["path"],timeout=30000)
                        update(item,status="File selected",note="Waiting for upload result.")

                        # Wait for network activity to settle after file selection (Drupal AJAX upload)
                        if auto_upload:
                            print(f"DEBUG: Waiting for network idle after auto-upload...")
                            try:
                                page.wait_for_load_state("networkidle", timeout=30000)
                                print("DEBUG: Network idle detected")
                            except Exception as e:
                                print(f"DEBUG: Network idle timeout (continuing anyway): {e}")
                            # Extra wait for Drupal AJAX to complete
                            time.sleep(2)

                        # Only click a configured button when automatic upload is not enabled.
                        upload_trigger = (cfg.get("upload_trigger") or "").strip()

                        if upload_trigger and not auto_upload:
                            button = page.locator(upload_trigger).first
                            button.wait_for(state="visible", timeout=30000)
                            button.wait_for(state="attached", timeout=30000)
                            button.click(timeout=30000)
                        # If the website requires a manual step (CAPTCHA, submit, confirmation),
                        # the browser stays visible and the user can complete it.
                        deadline=time.time()+cfg["wait_seconds"]
                        found=""
                        expected=item["filename"].lower()
                        first_loop = True

                        # Dump all links on first iteration for debugging
                        try:
                            all_links = page.evaluate("""() => {
                                return Array.from(document.querySelectorAll('a[href*=".pdf"], a[href$=".pdf"]')).map(a => ({
                                    href: a.href,
                                    text: a.innerText,
                                    html: a.outerHTML.substring(0, 200)
                                }));
                            }""")
                            print(f"DEBUG: All PDF links on page: {all_links}")
                        except Exception as e:
                            print(f"DEBUG: Error dumping links: {e}")

                        while time.time()<deadline and not state.stop_event.is_set():
                            # Drupal updates its managed-file widget asynchronously.
                            # Check its hidden file ID and inspect configured + generic PDF anchors.
                            fid_present=False
                            for fs in ['input[type="hidden"][name*="[fids]"]',
                                       'input[data-drupal-selector$="-fids"]',
                                       'input[name*="field_apply_resume"][type="hidden"]',
                                       'input[type="hidden"]']:
                                try:
                                    loc=page.locator(fs)
                                    count = loc.count()
                                    for j in range(min(count,20)):
                                        name_attr = loc.nth(j).get_attribute("name") or ""
                                        val = (loc.nth(j).get_attribute("value") or "").strip()
                                        if val and first_loop:
                                            print(f"DEBUG: Hidden field {fs}: name={name_attr}, value={val}")
                                        if "fid" in name_attr.lower() and val:
                                            fid_present=True
                                            if first_loop:
                                                print(f"DEBUG: Found FID field with value: {val}")
                                            break
                                except Exception as e:
                                    if first_loop:
                                        print(f"DEBUG: Error checking FID selector {fs}: {e}")
                                if fid_present:
                                    break

                            selectors=[]
                            if cfg["link_selector"]:
                                selectors.append(cfg["link_selector"])
                            selectors.extend([
                                ".js-form-managed-file a[href]",
                                ".js-webform-document-file a[href]",
                                ".file-link a[href]",
                                'span[class*="file"] a[href]',
                                'a[href$=".pdf"]',
                                'a[href*=".pdf?"]',
                                'a[href*=".pdf"]',
                            ])
                            seen=set()
                            for css in selectors:
                                try:
                                    loc=page.locator(css)
                                    count = loc.count()
                                    if count > 0 and first_loop:
                                        print(f"DEBUG: Found {count} links matching selector: {css}")
                                    for n in range(min(count,300)):
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
                                        matches_name=(
                                            basename==expected
                                            or basename.endswith("__"+expected)
                                            or label==expected
                                            or label.endswith("__"+expected)
                                        )
                                        if first_loop:
                                            print(f"DEBUG: Link - href={absolute}, label={label}, basename={basename}, matches={matches_name}")
                                        if safe_link(absolute) and matches_name:
                                            found=absolute
                                            print(f"DEBUG: ✓ MATCH FOUND! URL: {found}")
                                            break
                                    if found:
                                        break
                                except Exception as e:
                                    if first_loop:
                                        print(f"DEBUG: Error checking selector {css}: {e}")
                                    continue
                            if found:
                                break
                            first_loop = False
                            time.sleep(1)
                        if found:
                            update(item,status="Captured",url=found,note="Filename matched the queued PDF.")
                            update(message=f"Captured {item['filename']}; closing tab and continuing.")
                            page.close()
                        elif state.stop_event.is_set():
                            update(item,status="Stopped",note="Stopped before URL capture.")
                            page.close();break
                        else:
                            update(item,status="Needs attention",note="No matching URL found. Complete required site steps or adjust selectors; inspect this browser tab.")
                            update(message=f"Paused on {item['filename']}. Complete required steps or inspect page; then stop this run.")
                            while not state.stop_event.is_set():time.sleep(1)
                            page.close();break
                    except Exception as e:
                        update(item,status="Failed",note=str(e)[:500])
                        update(message=f"Failed on {item['filename']}; browser left open for inspection.")
                        while not state.stop_event.is_set():time.sleep(1)
                        page.close();break
                    time.sleep(1.5)
            finally:
                context.close();browser.close()
    except Exception as e:
        update(message=f"Automation error: {e}")
    finally:
        with state.lock:
            state.running=False
            if state.message.startswith("Captured"):state.message="Queue finished."
