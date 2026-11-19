#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAKUB-KETEBE-SERVISI (HF-Space icinde yasayan katman)
====================================================
Iki-yuzlu tek-sunucu:
  1) WEB:  /  → karanlik-TR sayfa; link yapistir → isi arkaplanda kurar;
           /api/talep, /api/durum/<id>, /api/dosya/<id>/<n>
  2) TG:   /webhook → Telegram guncellemeleri (TG_TOKEN env-varsa aktif)
           /tg-kur  → setWebhook (Space-URL'sine cakar)
Nabiz: /nabiz (cron-job.orgKeep-alive icin)
Is-kurallari: eser-je-Seri 1-ayni anda (KILIT); isi-dosyalari /tmp'de; eski-is-silme.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse)

UA = {"User-Agent": "YakubBotKetebeIndir/1.1"}
API = "https://api.telegram.org"
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()

CALISMA = Path(tempfile.gettempdir()) / "yakub_isler"
CALISMA.mkdir(parents=True, exist_ok=True)

_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("kc", str(_here / "ketebe-ceker.py"))
KC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KC)

app = FastAPI(title="Yakub Ketebe Indir")
KILIT = threading.Lock()
ISLER: dict[str, dict] = {}
MAX_IS = 8

# ---------------- cekirdek-is ----------------
def eser_isi(iid: str, url: str):
    with KILIT:
        try:
            ISLER[iid]["durum"] = "analiz"
            baslik, yollar = KC.eser_analiz(url)
            ISLER[iid]["ad"] = baslik[:90]
            ISLER[iid]["durum"] = "indiriliyor"
            out = CALISMA / iid
            out.mkdir(parents=True, exist_ok=True)
            klasorler = KC.eser_cek(url, out)
            dosyalar = []
            for k in klasorler:
                dosyalar += sorted(Path(k).glob("*_TAM.jpg"))
            if not dosyalar:
                ISLER[iid]["durum"] = "hata"
                ISLER[iid]["hata"] = "goruntu bulunamadi"
                return
            ISLER[iid]["durum"] = "hazir"
            ISLER[iid]["dosyalar"] = [str(d) for d in dosyalar]
        except Exception as e:
            ISLER[iid]["durum"] = "hata"
            ISLER[iid]["hata"] = str(e)[:220]


def is_tempizle():
    dirs = sorted([d for d in CALISMA.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime)
    for esk in dirs[:-MAX_IS]:
        shutil.rmtree(esk, ignore_errors=True)


def url_valid(metin: str):
    m = re.search(r"ketebe\.org/eserler/(\d{1,7})", metin or "")
    if m:
        return "https://beta.ketebe.org/eserler/" + m.group(1)
    if re.fullmatch(r"\d{1,7}", (metin or "").strip()):
        return "https://beta.ketebe.org/eserler/" + metin.strip()
    return None


# ---------------- WEB ----------------
SAYFA = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yakub Ketebe İndir</title><style>
body{margin:0;font-family:system-ui,'Segoe UI',sans-serif;background:#161b26;color:#d7dde8;
display:flex;min-height:100vh;align-items:center;justify-content:center}
.k{background:#202530;border:1px solid #2c3444;border-radius:16px;padding:28px;width:min(94vw,520px)}
h1{font-size:1.25rem;margin:0 0 6px;color:#e8b45a}small{color:#8b94a6}
input{width:100%;box-sizing:border-box;margin:14px 0;padding:12px;border-radius:10px;
border:1px solid #39415a;background:#171c27;color:#fff;font-size:1rem}
button{width:100%;padding:12px;border:0;border-radius:10px;background:#e8b45a;color:#20242e;
font-weight:700;font-size:1rem;cursor:pointer}
#s{margin-top:14px;font-size:.95rem;line-height:1.5}
a.d{display:block;margin:8px 0;padding:10px;background:#2a3347;color:#bcd3ff;border-radius:10px;
text-decoration:none;text-align:center}
.ok{color:#8fd694}.er{color:#e08a8a}.sp{color:#e8b45a}
</style></head><body><div class="k">
<h1>🏛 Yakub Ketebe İndir</h1>
<small>beta.ketebe.org eserlerinin <b>tam-çözünürlük</b> taramaları — kayıpsız JPG</small>
<input id="u" placeholder="Eser numarası veya linki (örn: 8680)">
<button onclick="basla()">İndirmeye Başla</button>
<div id="s"></div></div>
<script>
const s=document.getElementById('s');
function bak(id,n){
 fetch('/api/durum/'+id).then(r=>r.json()).then(j=>{
  if(j.durum=='hazir'){
    s.innerHTML='<div class="ok">✔ Hazır: '+(j.ad||'')+'</div>'+
      j.dosyalar.map((f,i)=>'<a class="d" href="/api/dosya/'+id+'/'+i+'" target="_blank">⬇ JPG-'+(i+1)+' indir</a>').join('');
  }else if(j.durum=='hata'){ s.innerHTML='<div class="er">✋ '+j.hata+' — tekrar dene</div>'; }
  else if(j.durum=='kuyruk'){ s.innerHTML='<div class="sp">⏳ Diğer eser bitiyor…</div>';
    setTimeout(()=>bak(id,n),2500); }
  else { s.innerHTML='<div class="sp">🫀 '+j.durum+'… ('+(++n)+' sn)</div>';
    setTimeout(()=>bak(id,n),1500); }
 });
}
function basla(){
 const v=document.getElementById('u').value.trim();
 if(!v){return;}
 s.innerHTML='<div class="sp">🕐 Görev açılıyor…</div>';
 fetch('/api/talep',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({url:v})}).then(r=>r.json()).then(j=>{
   if(j.id){ bak(j.id,0); } else { s.innerHTML='<div class="er">'+(j.hata||'?')+'</div>'; }
 }).catch(e=>{ s.innerHTML='<div class="er">Bağlantı hatası</div>'; });
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def kok():
    return SAYFA


@app.get("/nabiz")
def nabiz():
    return PlainTextResponse("okay " + time.strftime("%H:%M:%S"))


@app.post("/api/talep")
async def talep(req: Request):
    try:
        govde = await req.json()
    except Exception:
        return JSONResponse({"hata": "bozuk-istek"}, status_code=400)
    url = url_valid(str(govde.get("url", "")))
    if not url:
        return JSONResponse({"hata": "ketebe-eser-linki/numarası-bekledim"}, status_code=400)
    is_tempizle()
    iid = uuid.uuid4().hex[:10]
    ISLER[iid] = {"durum": "kuyruk", "ad": ""}
    threading.Thread(target=eser_isi, args=(iid, url), daemon=True).start()
    return {"id": iid, "url": url}


@app.get("/api/durum/{iid}")
def durum(iid: str):
    kayit = ISLER.get(iid)
    if not kayit:
        return JSONResponse({"durum": "hata", "hata": "is-kaydi-yok (zaman-asmasi olmus)"}, status_code=404)
    don = {"durum": kayit["durum"], "ad": kayit.get("ad", "")}
    if kayit["durum"] == "hazir":
        don["dosyalar"] = kayit.get("dosyalar", [])
    if kayit["durum"] == "hata":
        don["hata"] = kayit.get("hata", "?")
    return don


@app.get("/api/dosya/{iid}/{n}")
def dosya(iid: str, n: int):
    kayit = ISLER.get(iid)
    if not kayit or kayit["durum"] != "hazir":
        return JSONResponse({"hata": "hazir-degil"}, status_code=404)
    liste = kayit.get("dosyalar", [])
    if n < 0 or n >= len(liste):
        return JSONResponse({"hata": "sira-yok"}, status_code=404)
    p = Path(liste[n])
    return FileResponse(str(p), media_type="image/jpeg", filename=p.name)


# ---------------- TELEGRAM-WEBHOOK ----------------
def tg_get(yol, params, zaman=30):
    q = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "%s/bot%s/%s?%s" % (API, TG_TOKEN, yol, q), headers=UA), timeout=zaman) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "description": str(e)}


def tg_doc(chat_id, p: Path, cap: str):
    bnd = "----Yakub" + uuid.uuid4().hex
    parts = [('--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n' % (bnd, chat_id)).encode(),
             ('--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n' % bnd).encode()
             + cap.encode("utf-8") + "\r\n".encode(),
             ('--%s\r\nContent-Disposition: form-data; name="document"; filename="' % bnd).encode()
             + p.name.encode("utf-8") + '"\r\nContent-Type: image/jpeg\r\n\r\n'.encode(),
             p.read_bytes(), ("\r\n--%s--\r\n" % bnd).encode()]
    rq = urllib.request.Request("%s/bot%s/sendDocument" % (API, TG_TOKEN), data=b"".join(parts),
                                headers={"Content-Type": "multipart/form-data; boundary=%s" % bnd})
    try:
        with urllib.request.urlopen(rq, timeout=180) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "description": str(e)}


def tg_bir(iid, url, chat_id):
    tg_get("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
    out = CALISMA / iid
    out.mkdir(parents=True, exist_ok=True)
    baslik, _y = KC.eser_analiz(url)
    klasorler = KC.eser_cek(url, out)
    fs = [f for k in klasorler for f in sorted(Path(k).glob("*_TAM.jpg"))]
    if not fs:
        tg_get("sendMessage", {"chat_id": chat_id, "text": "ⓘ görsel bulamadım (%s)" % iid})
        return
    for i, d in enumerate(fs, 1):
        tg_get("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
        cap = "🏛 %s\n📐 TAM-ÇÖZÜNÜRLÜK • %d KB [%d/%d]" % (baslik[:60], d.stat().st_size // 1024, i, len(fs))
        tg_doc(chat_id, d, cap)
    shutil.rmtree(out, ignore_errors=True)


TG_BEK = (5, 10)


def tg_job(iid_url_chat):
    """v1.2: oto-tekrar (5,10 sn) + nazik baglanti uyarlari."""
    iid, url, chat_id = iid_url_chat
    EB = getattr(KC, "EserBulunamadi", ())
    GH = getattr(KC, "GeciciHata", ())
    sebep = ""
    for deneme in range(1, 4):
        if deneme > 1:
            bekle = TG_BEK[deneme - 2]
            cumle = ("🌐 İnternet bağlantısında kopukluk görünüyor…\n%d sn içinde kendiliğimden %d. denemeye geçiyorum."
                     if sebep == "baglanti" else
                     "🔁 Geçici aksama…\n%d sn içinde otomatik %d. denemeye geçiyorum.") % (bekle, deneme)
            tg_get("sendMessage", {"chat_id": chat_id, "text": cumle})
            time.sleep(bekle)
        try:
            tg_bir(iid, url, chat_id)
            return
        except Exception as e:
            if EB and isinstance(e, EB):
                tg_get("sendMessage", {"chat_id": chat_id, "text": "🔎 Bu numarada eser görünmüyor. Linki/numarayı kontrol eder misin?"})
                return
            ag = isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))
            sebep = "baglanti" if ag else "gecici"
    site = tg = False
    try:
        import socket as _s
        _s.create_connection(("beta.ketebe.org", 443), timeout=4).close(); site = True
    except Exception:
        pass
    try:
        import socket as _s
        _s.create_connection(("api.telegram.org", 443), timeout=4).close(); tg = True
    except Exception:
        pass
    if site and not tg:
        m = "🏰 Ketebe sitesine şu an ulaşılamıyor (site taraflı). 10 dk sonra tekrar dener misin?"
    elif not site:
        m = "😕 Denemelerde olmadı — bağlantıda sorun görünüyor (site/biz tarafı). Biraz sonra tekrar dener misin?"
    else:
        m = "😕 Denemelerde olmadı; Ketebe yoğun olabilir. Birkaç dakika sonra tekrar dener misin?"
    tg_get("sendMessage", {"chat_id": chat_id, "text": m})


@app.post("/webhook")
async def webhook(req: Request):
    if not TG_TOKEN:
        return PlainTextResponse("tg-kapali", status_code=200)
    try:
        upd = await req.json()
    except Exception:
        return PlainTextResponse("ok")
    m = upd.get("message") or {}
    chat_id = (m.get("chat") or {}).get("id")
    metin = (m.get("text") or "").strip()
    if chat_id and metin:
        url = url_valid(metin)
        if url:
            tg_get("sendMessage", {"chat_id": chat_id, "text": "🔍 %s → tam-çözünürlük hazırlanıyorum (10-60 sn)" % url.rsplit("/", 1)[-1]})
            iid = uuid.uuid4().hex[:10]
            ISLER[iid] = {"durum": "tg", "ad": ""}
            threading.Thread(target=tg_job, args=((iid, url, chat_id),), daemon=True).start()
        elif metin.startswith("/start"):
            tg_get("sendMessage", {"chat_id": chat_id, "text": "📚 Yakub Ketebe İndir!\nEser numarası veya linki yolla (örn 8680)."})
        else:
            tg_get("sendMessage", {"chat_id": chat_id, "text": "Eser numarası/linki bekledim (örn: 8680)"})
    return PlainTextResponse("ok")


@app.get("/tg-kur")
def tg_kur(req: Request):
    if not TG_TOKEN:
        return PlainTextResponse("TG_TOKEN env-yok", status_code=500)
    hedef = str(req.base_url).rstrip("/") + "/webhook"
    j = tg_get("setWebhook", {"url": hedef, "allowed_updates": json.dumps(["message"]), "drop_pending_updates": "false"})
    return JSONResponse({"hedef": hedef, "tg": j})
