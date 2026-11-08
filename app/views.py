import csv,io,uuid
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse,HttpResponse
from django.shortcuts import render,redirect
from django.views.decorators.http import require_POST
from . import state
from .runner_fixed import run_queue

def home(request):
    return render(request,"index.html")

@require_POST
def queue_pdfs(request):
    with state.lock:
        if state.running: return HttpResponse("Stop the current run first.",status=409)
        state.items.clear()
        for f in request.FILES.getlist("pdfs"):
            if not f.name.lower().endswith(".pdf"): continue
            name=Path(f.name).name
            path=settings.UPLOAD_DIR/(uuid.uuid4().hex+"__"+name)
            with path.open("wb") as out:
                for chunk in f.chunks(): out.write(chunk)
            state.items.append({"filename":name,"path":str(path),"status":"Queued","url":"","note":""})
        state.message=f"{len(state.items)} PDF(s) queued."
        state.config={
            "site_url":request.POST.get("site_url","").strip(),
            "file_selector":request.POST.get("file_selector","").strip(),
            "link_selector":request.POST.get("link_selector","").strip(),
            "upload_trigger":request.POST.get("upload_trigger","").strip(),
            "wait_seconds":max(10,min(600,int(request.POST.get("wait_seconds","120") or 120))),
        }
    return redirect("/")

@require_POST
def start(request):
    import threading
    with state.lock:
        if state.running: return JsonResponse({"error":"Already running."},status=409)
        if not state.items: return JsonResponse({"error":"Queue PDFs first."},status=400)
        if not state.config.get("site_url","").startswith(("https://","http://")):
            return JsonResponse({"error":"Enter a valid website URL first."},status=400)
        state.stop_event.clear();state.running=True;state.message="Starting browser..."
        state.worker=threading.Thread(target=run_queue,daemon=True);state.worker.start()
    return JsonResponse({"ok":True})

@require_POST
def stop(request):
    state.stop_event.set()
    return JsonResponse({"ok":True})

def status(request):
    with state.lock:
        rows=[{k:v for k,v in x.items() if k!="path"} for x in state.items]
        return JsonResponse({"running":state.running,"message":state.message,"items":rows})

def export_csv(request):
    s=io.StringIO();w=csv.writer(s);w.writerow(["Filename","Status","URL","Note"])
    with state.lock:
        for x in state.items:w.writerow([x["filename"],x["status"],x["url"],x["note"]])
    r=HttpResponse(s.getvalue(),content_type="text/csv");r["Content-Disposition"]='attachment; filename="pdf_links.csv"';return r
