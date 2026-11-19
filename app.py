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
                dosyalar += sorted(Path(k).glob("*_TAM*.jpg"))
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


@app.get("/api/isler")
def api_isler():
    with JOBS_K:
        return {k: {"durum": v.get("durum"), "url": v.get("url")} for k, v in JOBS.items()}


@app.get("/api/meta/{eser}")
def api_meta(eser: str):
    u = "https://beta.ketebe.org/eserler/" + eser.strip("/ ")
    try:
        return KC.eser_meta(u)
    except Exception as e:
        return JSONResponse({"hata": str(e)[:160]}, status_code=400)


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
        with urllib.request.urlopen(rq, timeout=600) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "description": str(e)}


JOBS: dict[str, dict] = {}
JOBS_K = threading.Lock()
LEDGER = CALISMA / "durum-defteri.json"


def _defter_yaz():
    try:
        with JOBS_K:
            oz = {k: {kk: v[kk] for kk in ("durum", "url", "chat", "t0", "sec") if kk in v} for k, v in JOBS.items()}
        LEDGER.write_text(json.dumps(oz, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _defter_oku():
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---- v1.5: BUTON-SECIM altsistemi ----
SECIM: dict[str, dict] = {}


def secim_kur(iid):
    SECIM[iid] = {"ev": threading.Event(), "sec": ""}


def sec_i_yaz(iid, sec):
    with JOBS_K:
        if iid in JOBS:
            JOBS[iid]["sec"] = sec


def secim_bekle(iid, tmo=600):
    s = SECIM.get(iid)
    if s and s["ev"].wait(tmo):
        return s["sec"] or "full"
    return "auto-full"


def cb_cevap(cb_id, metin):
    tg_get("answerCallbackQuery", {"callback_query_id": cb_id, "text": metin[:190]})


def _is_durum(iid, durum):
    with JOBS_K:
        if iid in JOBS:
            JOBS[iid]["durum"] = durum
            JOBS[iid]["son"] = time.time()
    _defter_yaz()


def _is_baslat(iid, url, chat_id, sifirdan=True):
    with JOBS_K:
        kayit = JOBS.setdefault(iid, {"durum": "kuyruk", "t0": time.time(), "son": time.time(), "rest": 0, "url": url, "chat": chat_id})
        if sifirdan:
            kayit.update({"rest": 0, "t0": time.time()})
    kaykay_sec = kayit.get("sec")
    t = threading.Thread(target=tg_job, args=((iid, url, chat_id), kaykay_sec), daemon=True)
    with JOBS_K:
        kayit["th"] = t
    _defter_yaz()
    t.start()
    return t


def _canbakici():
    """Thread sessizce olmussa isleri gozler; 1 kez 5-sn-molayla yeniden dogurtur."""
    while True:
        time.sleep(5)
        su = time.time()
        for iid in list(JOBS.keys()):
            with JOBS_K:
                j = JOBS.get(iid)
            if not j:
                continue
            if j["durum"] in ("bitti", "hata"):
                if su - j.get("son", 0) > 3600:
                    with JOBS_K:
                        JOBS.pop(iid, None)
                continue
            th = j.get("th")
            if th is not None and not th.is_alive() and su - j.get("son", 0) > 8:
                if j.get("rest", 0) < 1:
                    with JOBS_K:
                        JOBS[iid]["rest"] = JOBS[iid].get("rest", 0) + 1
                    tg_get("sendMessage", {"chat_id": j["chat"],
                                           "text": "👀 Başlangıçta bir aksama fark ettim — 5 sn içinde yeniden başlatıyorum…" if su - j["t0"] < 45 else "👀 İş ortasında sessizlik fark ettim — 5 sn içinde yeniden deniyorum…"})
                    time.sleep(5)
                    _is_baslat(iid, j["url"], j["chat"])
            elif th is not None and th.is_alive() and j["durum"] != "soru" and su - j.get("son", 0) > 90:
                tg_get("sendMessage", {"chat_id": j["chat"], "text": "🫀 Hâlâ çalışıyorum (büyük eser, sabır)…"})
                with JOBS_K:
                    JOBS[iid]["son"] = time.time()


@app.on_event("startup")
def _gozcu_cagri():
    threading.Thread(target=_canbakici, daemon=True).start()
    # v1.4 RESTART-SAGLIKCI: instance yenilendiyse yarim-kalan islere "devam" der
    def _recover():
        time.sleep(6)
        for iid, kay in _defter_oku().items():
            if kay.get("durum") in ("kuyruk", "analiz", "indirme", "gonderim", "tekrar"):
                tg_get("sendMessage", {"chat_id": kay["chat"],
                                       "text": "🔁 Sunucu kısa bir bakım geçirdi; işin kaldığı yerden sürüyor…"})
                _is_baslat(iid, kay["url"], kay["chat"], sifirdan=False)
    threading.Thread(target=_recover, daemon=True).start()


def birlestir(fs, out_klasor):
    """Bant-JPG'leri piksel-perfect dikey-birleştir → tek-ORIJINAL jpg. (Küçük-RAM: sıra-dekod)"""
    from PIL import Image
    olcer = []
    for d in fs:
        with Image.open(d) as im:
            olcer.append(im.size)
    gen = min(w for w, _ in olcer)
    ty = sum(h for _, h in olcer)
    if gen * ty > 85_000_000:
        return None
    cnv = Image.new("RGB", (gen, ty))
    y = 0
    for d, (gw, gh) in zip(fs, olcer):
        with Image.open(d) as im:
            cnv.paste(im if im.mode == "RGB" else im.convert("RGB"), (0, y))
        y += gh
        import gc as _g
        _g.collect()
    kok = fs[0].name.split("__")[0]
    bir = Path(out_klasor) / ("%s__BIRLESIK.jpg" % kok)
    cnv.save(bir, quality=92)
    del cnv
    import gc as _g
    _g.collect()
    return bir


def tg_bir(iid, url, chat_id, sec="full", meta=None, dev=False, olcu=None):
    """Tek-deneme: ACK -> (full|half) cekim -> doc'lar -> kunye."""
    EB = getattr(KC, "EserBulunamadi", ())
    _is_durum(iid, "analiz")
    tg_get("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
    out = CALISMA / iid
    out.mkdir(parents=True, exist_ok=True)
    if meta is None:
        try:
            meta = KC.eser_meta(url)
        except Exception:
            meta = {}
    baslik = meta.get("baslik") or ""
    etiket = "ORIJINAL" if sec == "full" else "YARIM-COZUNURLUK"
    ek_dev = ("\n🐉 DEV-ESER: %dx%d — 1-3 dk, telaş yok (susmuyorum)" % olcu) if (dev and olcu and sec == "full") else ""
    _is_durum(iid, "indirme")
    tg_get("sendMessage", {"chat_id": chat_id,
                           "text": ("▶️ İndirme BAŞLADI (%s): %s\n⏳ tahmini 10–60 sn%s"
                                    % (etiket, baslik or url.rsplit('/', 1)[-1], ek_dev))[:400]})
    ofset = 0 if sec == "full" else -1
    try:
        klasorler = KC.eser_cek(url, out, seviye_ofseti=ofset, serit_hedef_mb=8)
    except Exception as e:
        if EB and isinstance(e, EB):
            raise
        if sec == "full" and dev:
            tg_get("sendMessage", {"chat_id": chat_id,
                                   "text": "💥 Tam-kalite havada kaldı (%s) — ⚡ yarısını hazırlıyorum…" % str(e)[:70]})
            klasorler = KC.eser_cek(url, out, seviye_ofseti=-1, serit_hedef_mb=8)
            etiket = "YARIM (yedek)"
        else:
            raise
    fs = [f for k in klasorler for f in sorted(Path(k).glob("*_TAM*.jpg"))]
    if not fs:
        raise RuntimeError("goruntu-uretilemedi")
    _is_durum(iid, "gonderim")
    basarisiz = []
    for i, d in enumerate(fs, 1):
        tg_get("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
        olcub = ""
        if sec != "full":
            try:
                from PIL import Image
                with Image.open(d) as imx:
                    olcub = " %dx%d" % imx.size
            except Exception:
                pass
        cap = "🏛 %s\n📐 %s%s • %d KB [%d/%d]" % ((baslik or "Eser")[:60],
                                                 "TAM-ÇÖZÜNÜRLÜK" if sec == "full" else "⚡ YARIM-ÇÖZÜNÜRLÜK",
                                                 olcub, d.stat().st_size // 1024, i, len(fs))
        try:
            tg_doc(chat_id, d, cap)
        except Exception:
            try:
                time.sleep(3); tg_doc(chat_id, d, cap + " (yeniden)")
            except Exception:
                basarisiz.append(d.name)
    if not basarisiz and len(fs) > 1:
        try:
            _is_durum(iid, "birlestirme")
            tg_get("sendMessage", {"chat_id": chat_id,
                                   "text": "🧵 Parçalar sohbete indi — üstüne TEK-PARÇA birleşik kopyayı da kuruyorum (1-2 dk)…"})
            print("   [i] BIRLESTIR basli: %d parca" % len(fs))
            tk = birlestir(fs, out)
            print("   [i] BIRLESTIR ok: %s (%d KB)" % (tk.name if tk else "-", tk.stat().st_size//1024 if tk else 0))
            if tk:
                tg_get("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
                tg_doc(chat_id, tk, "🖼 TEK PARÇA — ORIJINAL birleşik • %d KB" % (tk.stat().st_size // 1024))
        except Exception as _be:
            print("   [i] BIRLESTIR HATA:", repr(_be)[:120])
            tg_get("sendMessage", {"chat_id": chat_id,
                                   "text": "ℹ️ Birleşik kopya bu denemedi kurulamadı; parçalar eksiksiz sohbette."})
    if basarisiz:
        tg_get("sendMessage", {"chat_id": chat_id,
                               "text": "⚠️ %d bölüm taşınmadı (%s) — az sonra tek-tek yenilerim." % (len(basarisiz), ", ".join(basarisiz)[:60])})
    else:
        ktext = ""
        try:
            ktext = KC.kunye_format(meta, url) if meta else ""
        except Exception:
            ktext = ""
        if ktext:
            tg_get("sendMessage", {"chat_id": chat_id, "text": "📘 ESER KÜNYESİ\n" + ktext})
        shutil.rmtree(out, ignore_errors=True)
    _is_durum(iid, "bitti")


TG_BEK = (5, 10)


def tg_job(iid_url_chat, resume_sec=None):
    """v1.6: dev-eserde BUTON-SORUSU (orijinal/yarisi) + oto-tekrar + nezaket."""
    iid, url, chat_id = iid_url_chat
    EB = getattr(KC, "EserBulunamadi", ())
    secim_kur(iid)
    meta = None
    try:
        meta = KC.eser_meta(url)
    except Exception as e:
        if EB and isinstance(e, EB):
            tg_get("sendMessage", {"chat_id": chat_id,
                                   "text": "🔎 Bu numarada eser görünmüyor. Linki/numarayı kontrol eder misin? (yayından kalkmış/dijitalleşmemiş olabilir)"})
            _is_durum(iid, "hata")
            SECIM.pop(iid, None)
            return
        meta = {}
    olcu = None
    try:
        _y = KC.eser_analiz(url)[1]
        if _y:
            _pa = _y[0].split("/")
            _m = KC.dzi_oku(_pa[-1].rsplit(".", 1)[0], "/".join(_pa[:2]))
            if _m:
                olcu = (_m[0], _m[1])
    except Exception:
        pass
    dev = bool(olcu and olcu[0] * olcu[1] > 12_000_000)
    sec = resume_sec or ""
    if not sec:
        with JOBS_K:
            sec = JOBS.get(iid, {}).get("sec", "")
    if not sec:
        sec = "full"
    if dev and resume_sec is None and not JOBS.get(iid, {}).get("sec"):
        kb = {"inline_keyboard": [[
            {"text": "🏛 Orijinal (%dx%d, 1-3 dk)" % olcu, "callback_data": "sec|%s|full" % iid},
            {"text": "⚡ Yarısı (%dx%d, 30-60 sn)" % (olcu[0] // 2, olcu[1] // 2), "callback_data": "sec|%s|half" % iid}]]}
        _is_durum(iid, "soru")
        tg_get("sendMessage", {"chat_id": chat_id,
                               "text": "🐉 DEV-ESER: %dx%d piksel. Hangisini istersin?\n(10 dk seçim yoksa ORİJİNAL'i getiririm)" % olcu,
                               "reply_markup": json.dumps(kb)})
        sec = secim_bekle(iid, 600)
        if sec == "auto-full":
            tg_get("sendMessage", {"chat_id": chat_id, "text": "⏰ Seçim gelmedi — ORİJİNAL'i getiriyorum."})
        SECIM.pop(iid, None)
        sec_i_yaz(iid, sec)
        _is_durum(iid, "kuyruk")
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
            tg_bir(iid, url, chat_id, sec=sec, meta=meta, dev=dev, olcu=olcu)
            return
        except Exception as e:
            if EB and isinstance(e, EB):
                tg_get("sendMessage", {"chat_id": chat_id,
                                       "text": "🔎 Bu numarada eser görünmüyor. Linki/numarayı kontrol eder misin?"})
                _is_durum(iid, "hata")
                return
            ag = isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))
            sebep = "baglanti" if ag else "gecici"
            _is_durum(iid, "tekrar")
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
        m = "😕 Denemelerde olmadı — bağlantıda sorun görünüyor. Biraz sonra tekrar dener misin?"
    else:
        m = "😕 Denemelerde olmadı; Ketebe yoğun olabilir. Birkaç dakika sonra tekrar dener misin?"
    tg_get("sendMessage", {"chat_id": chat_id, "text": m})
    _is_durum(iid, "hata")


@app.post("/webhook")
async def webhook(req: Request):
    if not TG_TOKEN:
        return PlainTextResponse("tg-kapali", status_code=200)
    try:
        upd = await req.json()
    except Exception:
        return PlainTextResponse("ok")
    cq = upd.get("callback_query")
    if cq:
        veri = cq.get("data") or ""
        if veri.startswith("sec|"):
            parcalar = veri.split("|")
            if len(parcalar) == 3:
                _tag, iid, sec = parcalar
                sx = SECIM.get(iid)
                if sx and not sx["ev"].is_set():
                    sx["sec"] = sec
                    sx["ev"].set()
                sec_i_yaz(iid, sec)
                cb_cevap(cq.get("id", ""), "🏛 Orijinal hazırlanıyor…" if sec == "full" else "⚡ Yarısı hazırlanıyor…")
        return PlainTextResponse("ok")
    m = upd.get("message") or {}
    chat_id = (m.get("chat") or {}).get("id")
    metin = (m.get("text") or "").strip()
    if chat_id and metin:
        url = url_valid(metin)
        if url:
            iid = uuid.uuid4().hex[:10]
            tg_get("sendMessage", {"chat_id": chat_id, "text": "🔍 %s → tam-çözünürlük hazırlanıyorum (10-60 sn)" % url.rsplit("/", 1)[-1]})
            _is_baslat(iid, url, chat_id)
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
