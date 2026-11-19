#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ketEBE-CEKER v1.1 — beta.ketebe.org eser sayfasindan TAM COZUNURLUK goruntuleri.
Yontem: DZI (DeepZoom) piramidinin en-ust katmanini karo-karo indir, piksel-hassas dik.
ZIRHLAR (v1.1) + KUNYE (v1.2) + SEVIYE-OFSETI (v1.3):
  * Eser-sayfasi-yok -> EserBulunamadi (ciril-404-asla-disari-cikmaz)
  * Piramit-yok/eksik -> proxy-yedek merdiveni: detail -> card (en-buyuk-mevcut)
  * Bozuk/eksik-karo (<%95 doluluk) -> montaj-red + yedek-merdiven
  * 5xx/timeout -> GeciciHata (retry'li)
Cikti: <eser-ad>__<W>x<H>_TAM.jpg (+ manifest.json)
Kullanim:
    python ketebe-ceker.py 8680 [baska-id/url...]  |  --liste dosya.txt  |  --cikti KLASOR
Stdlib-only (+Pillow varsa tek-dosya-JPG; yoksa tiles/+montaj.html).
"""
from __future__ import annotations

import argparse, concurrent.futures as cf, html as htmlmod, io, json, math, os
import re, sys, time, urllib.request, urllib.error
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KetEBE-Ceker/1.1"}
DELAY = 0.12
__version__ = "1.3"


class EserHata(Exception):
    """Insan-okur talimatli hata-tabani."""


class EserBulunamadi(EserHata):
    pass


class GeciciHata(EserHata):
    pass


def _insansi_hata(e: Exception) -> EserHata:
    if isinstance(e, urllib.error.HTTPError):
        k = e.code
        if k == 404:
            return EserBulunamadi("Eser sayfasi/kaynagi bulunamadi (404). Numara-veya-linki kontrol et; eser yayindan kalkmis olabilir.")
        if k in (429, 500, 502, 503, 504):
            return GeciciHata("Site yogun/gecicengorunuyor (HTTP %d); kisa moladan sonra tekrar dene." % k)
        return EserHata("HTTP %d: %s" % (k, getattr(e, "reason", "?")))
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return GeciciHata("Baglanti sorunu (%s); interneti/baglantiyi kontrol edip tekrar dene." % str(e)[:60])
    return EserHata(str(e)[:160])


def get(url, ikinci=3, zaman=40):
    son = None
    for d in range(ikinci):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=zaman) as r:
                return r.read()
        except Exception as e:
            son = e
            if isinstance(e, urllib.error.HTTPError) and e.code == 404 and ikinci == 1:
                raise
            time.sleep(0.6 * (d + 1))
    raise son


def eser_analiz(url):
    """Sayfadan butun master-goruntu kayitlarini cikar. 404/eksik -> EserBulunamadi."""
    try:
        ham = get(url).decode("utf-8", errors="replace")
    except Exception as e:
        raise _insansi_hata(e)
    yollar = set(re.findall(r"media\.ketebe\.org/i/[a-z]+/masters/([0-9]{4}/[0-9]{2}/[a-f0-9\-]+\.jpg)", ham))
    for m in re.findall(r'(?:r2_key|dzi_key)["\\\s,:]+(?:masters|dzi)/([0-9]{4}/[0-9]{2}/[a-f0-9\-]+?\.(?:jpg|dzi))', ham):
        yollar.add(m)
    yollar = {y for y in yollar if y.endswith(".jpg")}
    t = re.search(r"<title>(.*?)</title>", ham, re.S)
    baslik = htmlmod.unescape(re.sub(r"\s+", " ", t.group(1)).strip()) if t else "eser"
    baslik = baslik.split("|")[0].strip(" .-") or "eser"
    if not yollar:
        raise EserBulunamadi("Sayfa acti ama Gorsel-kaydi gorunmuyor; bu eser islenmemis olabilir.")
    return baslik, sorted(yollar)




# ---------------- kunye (v1.2) ----------------
def _ld_artwork(ham):
    """Sayfadaki JSON-LD @graph icerisindeki VisualArtwork dugumu (yoksa {})."""
    for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', ham, re.S):
        try:
            g = json.loads(b).get("@graph") or []
        except Exception:
            continue
        for dugum in g:
            if isinstance(dugum, dict) and dugum.get("@type") == "VisualArtwork":
                return dugum
    return {}


def _katkilar(ham):
    """'Katkida bulunanlar' bolumundeki (ad, meta-satiri) ciftleri."""
    cikti = []
    i = ham.find("Katkıda bulunanlar")
    if i < 0:
        return cikti
    seg = ham[i:i + 4000]
    for li in re.findall(r"<li.*?</li>", seg, re.S):
        sp = [htmlmod.unescape(re.sub("<[^>]+>", " ", x)).strip() for x in
              re.findall(r"<span[^>]*>(.*?)</span>", li, re.S)]
        sp = [re.sub(r"\s+", " ", x) for x in sp if x]
        if sp:
            ad = sp[0]
            meta = sp[1] if len(sp) > 1 else ""
            cikti.append((ad[:70], meta[:110]))
    return cikti


def _uzun_paragraflar(ham):
    """Kunye-degeri uzun 'icerik/ornek metin' paragraflari (varsa)."""
    icerik_bas = ham.find("Katkıda bulunanlar")
    tur_bas = ham.find("Eser türü")
    dilim = ham[icerik_bas: tur_bas if tur_bas > icerik_bas else icerik_bas + 9000]
    paragraf = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", dilim, re.S):
        metin = htmlmod.unescape(re.sub("<[^>]+>", " ", p))
        metin = re.sub(r"\s+", " ", metin).strip()
        if len(metin) >= 70:
            paragraf.append(metin)
    return paragraf


def eser_meta(url):
    """Eser-soylu bilgisi: baslik, alternatif, turler, malzeme, sanatcilar, aciklama."""
    try:
        ham = get(url).decode("utf-8", errors="replace")
    except Exception as e:
        raise _insansi_hata(e)
    ld = _ld_artwork(ham)
    alternatif = []
    for a in ld.get("alternateName") or []:
        if isinstance(a, str) and a.strip():
            alternatif.append(a.strip())
    yaraticilar = []
    for c in ld.get("creator") or []:
        if isinstance(c, dict) and c.get("name"):
            yaraticilar.append(str(c["name"])[:70])
    yaraticilar = yaraticilar or [ad for ad, _m in _katkilar(ham)]
    meta_satirlari = [m for _a, m in _katkilar(ham) if m]
    icerik = _uzun_paragraflar(ham)
    turler = [str(t) for t in (ld.get("artform") or []) if str(t).strip()]
    malzeme = [str(t) for t in (ld.get("artMedium") or []) if str(t).strip()]
    return {
        "baslik": str(ld.get("name") or "")[:90],
        "alternatif": alternatif[:3],
        "turler": turler[:6],
        "malzeme": malzeme[:6],
        "sanatcilar": yaraticilar[:4],
        "meta_satirlari": meta_satirlari[:3],
        "icerik": " ".join(icerik[:2])[:420],
        "ozet": str(ld.get("description") or "")[:220],
    }


def kunye_format(meta, url):
    """Eser-kunyesi -> insan-dostu TR metni (TG mesaji)."""
    satir = []
    if meta.get("baslik"):
        satir.append("🏛 %s" % meta["baslik"])
    for a in meta.get("alternatif", []):
        satir.append("🔤 %s" % a)
    for ad in meta.get("sanatcilar", []):
        satir.append("👤 %s" % ad)
    for ms in meta.get("meta_satirlari", []):
        satir.append("📅 %s" % ms)
    if meta.get("turler"):
        satir.append("📂 Eser türü: %s" % ", ".join(meta["turler"]))
    if meta.get("malzeme"):
        satir.append("🧪 Teknik-malzeme: %s" % ", ".join(meta["malzeme"]))
    govde = meta.get("icerik") or meta.get("ozet")
    if govde:
        satir.append("\n📝 %s" % govde)
    if url:
        satir.append("🔗 %s" % url)
    metin = "\n".join(satir).strip()
    return metin[:1100] if metin else ""

def dzi_oku(uuid, tarih):
    """DZI metadata -> (W,H,ts,ov,fmt) ya da None (piramit-yok)."""
    try:
        xml = get("https://media.ketebe.org/dzi/%s/%s.dzi" % (tarih, uuid), ikinci=1, zaman=20).decode("utf-8", "replace")
    except Exception:
        return None
    if "<Image" not in xml:
        return None
    def attr(tag, ad):
        m = re.search(r"<%s[^>]*\b%s=\"(\d+)\"" % (tag, ad), xml)
        return int(m.group(1)) if m else None
    W = attr("Size", "Width"); H = attr("Size", "Height")
    if not W or not H:
        return None
    m = re.search(r'TileSize="(\d+)"', xml); ts = int(m.group(1)) if m else 256
    m = re.search(r'Overlap="(\d+)"', xml);  ov = int(m.group(1)) if m else 0
    m = re.search(r'Format="(\w+)"', xml);   fmt = m.group(1) if m else "jpg"
    return W, H, ts, ov, fmt


def karo_indir(u):
    for d in range(3):
        try:
            return get(u, ikinci=1, zaman=30)
        except Exception as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                return None
            time.sleep(0.8 * (d + 1))
    return None


def dik_dizi_stitch(tiles, W, H, ts, ov, cols, rows, hedef, min_doluluk=0.95):
    """Feather'li montaj. Doluluk<min -> ValueError (yedek-merdivene dus)."""
    from PIL import Image
    gercek = {k: v for k, v in tiles.items() if v}
    doluluk = len(gercek) / float(cols * rows)
    if doluluk < min_doluluk or not gercek:
        raise ValueError("karolar eksik (%d/%d)" % (len(gercek), cols * rows))
    cnv = Image.new("RGB", (W, H))
    for r in range(rows):
        for c in range(cols):
            veri = gercek.get((c, r))
            if not veri:
                continue
            try:
                t = Image.open(io.BytesIO(veri)); t.load()
            except Exception:
                continue
            cx0 = ov if c > 0 else 0
            cy0 = ov if r > 0 else 0
            t2 = t.crop((cx0, cy0, t.width, t.height))
            ox, oy = c * ts - (ov if c > 0 else ov) + cx0, r * ts - (ov if r > 0 else ov) + cy0
            if ox >= W or oy >= H:
                continue
            cnv.paste(t2, (ox, oy))
            if c > 0 and ov > 0:
                sol = cnv.crop((ox - 1, oy, ox, oy + t2.height))
                sag = cnv.crop((ox + 1, oy, ox + 2, oy + t2.height))
                if sag.size[0] > 0:
                    cnv.paste(Image.blend(sol, sag, 0.5), (ox, oy))
            if r > 0 and ov > 0:
                ust = cnv.crop((ox, oy - 1, ox + t2.width, oy))
                alt = cnv.crop((ox, oy + 1, ox + t2.width, oy + 2))
                if alt.size[1] > 0:
                    cnv.paste(Image.blend(ust, alt, 0.5), (ox, oy))
    cnv.save(hedef, quality=95, optimize=True)
    return doluluk


def yedek_proxy(tarih, uuid_str, hedef):
    """DZI-yok/bozuk -> proxy-variant merdiveni (en-buyuk-mevcut). Don: (yol, mod-adi)"""
    from PIL import Image
    for v, ad in (("detail", "EN-BUYUK-MEVCUT"), ("card", "orta-boy")):
        try:
            veri = get("https://media.ketebe.org/i/%s/masters/%s/%s.jpg" % (v, tarih, uuid_str), ikinci=2)
            im = Image.open(io.BytesIO(veri)); im.load(); im.verify()
            Path(hedef).write_bytes(veri)
            return Path(hedef), ad
        except Exception:
            continue
    raise EserBulunamadi("Ne piramit ne proxy-gorsel erisilebilir; eser henuz islenmemis olabilir.")


def eser_cek(url, cikti_kok, seviye_ofseti=0):
    """-> uretilen dosya-yollari (str list). Hata-insan-dostu EserHata agaci.
    seviye_ofseti=-1 -> piramidin bir-alt katmani (yaklasik yarim olculer, 4x hizli)."""
    cikti_kok = Path(cikti_kok); cikti_kok.mkdir(parents=True, exist_ok=True)
    baslik, yollar = eser_analiz(url)
    eser_no = str(url).rstrip("/").rsplit("/", 1)[-1]
    guvenli = re.sub(r"[^\w\- ]", "", baslik).strip().replace(" ", "_")[:60] or ("eser_" + eser_no)
    ciktilar = []
    for n, yol in enumerate(yollar, 1):
        par = yol.split("/")
        tarih = "/".join(par[:2]); uuid_str = par[-1].rsplit(".", 1)[0]
        meta = dzi_oku(uuid_str, tarih)
        klasor = cikti_kok / ("%s__k%d" % (guvenli, n))
        klasor.mkdir(parents=True, exist_ok=True)
        uretildi = None
        if meta:
            W, H, ts, ov, fmt = meta
            ust = max(1, math.ceil(math.log2(max(W, H, 1))))          # teorik tep katalog
            efektif = max(1, ust + seviye_ofseti)
            # empirik seviye saglamasi (secilen civarinda)
            mx = efektif
            for seviye in (efektif, efektif - 1, efektif + 1):
                if seviye < 1:
                    continue
                p = "https://media.ketebe.org/dzi/%s/%s_files/%d/0_0.%s" % (tarih, uuid_str, seviye, fmt)
                try:
                    get(p, ikinci=1, zaman=20); mx = seviye; break
                except Exception:
                    continue
            # secilen katmanin gercek olculeri: ust katmana gore 2^fark oranla
            fark = ust - mx
            wl = math.ceil(W / (2 ** fark))
            hl = math.ceil(H / (2 ** fark))
            cols, rows = math.ceil(wl / ts), math.ceil(hl / ts)
            base = "https://media.ketebe.org/dzi/%s/%s_files/%d" % (tarih, uuid_str, mx)
            jobs = [(c, r, "%s/%d_%d.%s" % (base, c, r, fmt)) for c in range(cols) for r in range(rows)]
            tiles = {}
            with cf.ThreadPoolExecutor(6) as ex:
                for (c, r), veri in zip([(c, r) for c, r, _ in jobs], ex.map(lambda j: karo_indir(j[2]), jobs)):
                    tiles[(c, r)] = veri
                time.sleep(0)
            time.sleep(DELAY)
            try:
                hedef = klasor / ("%s__%dx%d_TAM.jpg" % (guvenli, wl, hl))
                dol = dik_dizi_stitch(tiles, wl, hl, ts, ov, cols, rows, hedef)
                print("   [%d] piramit-stitch %dx%d (%.0f%% karo) -> %s (%.0f KB)"
                      % (n, wl, hl, dol * 100, hedef.name, hedef.stat().st_size / 1024))
                uretildi = hedef
            except ValueError as e:
                print("   ! piramit-yetersiz (%s) -> yedek-merdivene" % e)
        if uretildi is None:
            hedef, mod = yedek_proxy(tarih, uuid_str, klasor / ("%s__YOKEDEK.jpg" % guvenli))
            print("   [%d] %s -> %s (%.0f KB)" % (n, mod, hedef.name, hedef.stat().st_size / 1024))
            uretildi = hedef
        ciktilar.append(str(klasor))
        (klasor / "manifest.json").write_text(json.dumps({
            "kaynak": url, "eser_no": eser_no, "baslik": baslik, "master_yolu": yol,
            "cocuk": uretildi.name, "surum": __version__,
            "tarih": time.strftime("%Y-%m-%d %H:%M")
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    return ciktilar


def main():
    ap = argparse.ArgumentParser(description="KetEBE tam-cozunurluk ceker v%s" % __version__)
    ap.add_argument("eserler", nargs="*", help="eser URL veya ID")
    ap.add_argument("--liste", help="URL listesi iceren dosya")
    ap.add_argument("--cikti", default=str(Path.home() / "Pictures" / "Ketebe"))
    args = ap.parse_args()
    urls = list(args.eserler)
    if args.liste:
        urls += [l.strip() for l in Path(args.liste).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    urls = [("https://beta.ketebe.org/eserler/" + u.rsplit("/", 1)[-1]) if u.isdigit() else u for u in urls]
    if not urls:
        print(__doc__); sys.exit(1)
    kok = Path(args.cikti); kok.mkdir(parents=True, exist_ok=True)
    tum = []
    for u in urls:
        try:
            tum += eser_cek(u, kok)
        except EserHata as e:
            print("! %s -> %s" % (u, e))
        except Exception as e:
            print("! %s beklenmedik: %s" % (u, str(e)[:160]))
    print("\nBITTI: %d klasor" % len(tum))
    for t in tum:
        print(t)


if __name__ == "__main__":
    main()
