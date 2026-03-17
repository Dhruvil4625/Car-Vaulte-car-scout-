import io
import json
import re
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote

from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from core.models import CarListing, CarListingAsset, CarListingImage


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "na"


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in {"car", "cars", "auto", "automobile", "view"}]


def _wikimedia_search(query: str, limit: int = 12) -> list[dict[str, str]]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 1600,
        "format": "json",
        "formatversion": 2,
    }
    url = f"https://commons.wikimedia.org/w/api.php?{urlencode(params)}"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 VehicleVaultBot/1.0"})
        with urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []

    out = []
    for page in ((data or {}).get("query") or {}).get("pages") or []:
        info = (page.get("imageinfo") or [{}])[0]
        mime = (info.get("mime") or "").lower()
        url = info.get("thumburl") or info.get("url")
        if url and mime.startswith("image/") and not mime.endswith("svg+xml"):
            out.append({"title": page.get("title") or "", "url": url, "mime": mime})
    return out


def _download_image(url: str) -> bytes | None:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 VehicleVaultBot/1.0"})
        with urlopen(req, timeout=8) as res:
            ctype = (res.headers.get("Content-Type") or "").lower()
            data = res.read()
            if data and len(data) > 4096:
                if "image" in ctype:
                    return data
                try:
                    Image.open(io.BytesIO(data))
                    return data
                except Exception:
                    return None
    except (URLError, HTTPError, TimeoutError, ValueError):
        return None
    except Exception:
        return None
    return None


def _title_score(title: str, required_tokens: list[str], preferred_tokens: list[str]) -> int:
    title_tokens = set(_tokens(title))
    if required_tokens and not all(t in title_tokens for t in required_tokens):
        return -1
    score = 0
    for t in required_tokens:
        if t in title_tokens:
            score += 3
    for t in preferred_tokens:
        if t in title_tokens:
            score += 2
    return score


def _fetch_internet_image(query: str, width: int = 1920, height: int = 1080, required_tokens: list[str] | None = None, preferred_tokens: list[str] | None = None) -> bytes | None:
    del width, height
    required_tokens = required_tokens or []
    preferred_tokens = preferred_tokens or []
    queries = [
        query,
        f"{query} car",
        f"{query} automobile",
    ]
    seen = set()
    for q in queries:
        candidates = _wikimedia_search(q)
        candidates.sort(key=lambda item: _title_score(item.get("title", ""), required_tokens, preferred_tokens), reverse=True)
        for item in candidates:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            data = _download_image(url)
            if data:
                return data
    return None

def _unsplash_url(query: str, size: str = "1600x900") -> str:
    q = quote(query.strip())
    return f"https://source.unsplash.com/{size}/?{q}"

def _fetch_unsplash_image(query: str, size: str = "1600x900") -> bytes | None:
    url = _unsplash_url(query, size=size)
    return _download_image(url)

def _synthetic_image(make: str, model: str, label: str, w: int = 1600, h: int = 900) -> bytes:
    bg = ((sum(ord(c) for c in (make or "")) % 200) + 30, (sum(ord(c) for c in (model or "")) % 200) + 30, 180)
    img = Image.new("RGB", (w, h), bg)
    from PIL import ImageDraw, ImageFont
    dr = ImageDraw.Draw(img)
    try:
        f1 = ImageFont.load_default()
    except Exception:
        f1 = None
    txt1 = f"{make} {model}".strip()
    txt2 = label.strip()
    dr.text((40, 40), txt1, fill=(255, 255, 255), font=f1, stroke_width=1, stroke_fill=(0,0,0))
    dr.text((40, 120), txt2, fill=(240, 240, 240), font=f1)
    return _to_jpg_bytes(img)


def _open_rgb(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img.convert("RGB")


def _center_crop_ratio(img: Image.Image, ratio_w: int, ratio_h: int, out_w: int, out_h: int) -> Image.Image:
    w, h = img.size
    target_ratio = ratio_w / ratio_h
    src_ratio = w / h if h else target_ratio

    if src_ratio > target_ratio:
        # too wide -> crop width
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        y0 = 0
        crop = img.crop((x0, y0, x0 + new_w, h))
    else:
        # too tall -> crop height
        new_h = int(w / target_ratio)
        x0 = 0
        y0 = (h - new_h) // 2
        crop = img.crop((x0, y0, w, y0 + new_h))

    return crop.resize((out_w, out_h), Image.LANCZOS)


def _to_jpg_bytes(img: Image.Image, quality: int = 88) -> bytes:
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=quality, optimize=True)
    return bio.getvalue()


def _spin_frames_from_base(img: Image.Image, frames: int = 8, out_w: int = 1280, out_h: int = 720) -> list[bytes]:
    # Synthetic spin from one internet image via subtle pan+zoom.
    base = _center_crop_ratio(img, 16, 9, out_w, out_h)
    bw, bh = base.size
    out = []

    for i in range(max(1, frames)):
        t = i / max(1, frames - 1)
        zoom = 1.0 + (0.06 * (0.5 - abs(t - 0.5)) * 2)  # mild zoom in middle
        cw = int(bw / zoom)
        ch = int(bh / zoom)
        # pan horizontally across frame sequence
        pan = int((t - 0.5) * 0.18 * bw)
        x0 = max(0, min(bw - cw, (bw - cw) // 2 + pan))
        y0 = max(0, min(bh - ch, (bh - ch) // 2))
        fr = base.crop((x0, y0, x0 + cw, y0 + ch)).resize((out_w, out_h), Image.LANCZOS)
        out.append(_to_jpg_bytes(fr))

    return out


def _save_shared_file(folder: str, filename: str, data: bytes) -> str:
    path = f"listing_images/generated/{folder}/{filename}"
    if default_storage.exists(path):
        return path
    return default_storage.save(path, ContentFile(data))


class Command(BaseCommand):
    help = "Fetch Wikimedia Commons photos and attach exterior/interior + spin + 360 media per listing with proper aspect ratios."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Optional listing limit")
        parser.add_argument("--spin-frames", type=int, default=8, help="Spin frames per interior/exterior")
        parser.add_argument("--force", action="store_true", help="Re-add even if media already exists")
        parser.add_argument("--keep-placeholders", action="store_true", help="Keep existing SVG placeholder images instead of replacing them")
        parser.add_argument("--make", type=str, default="", help="Only process this make (e.g., BMW)")
        parser.add_argument("--model", type=str, default="", help="Only process this exact model")
        parser.add_argument("--strict-model", action="store_true", help="Require make+model token match from Wikimedia and skip inaccurate fallbacks")
        parser.add_argument("--no-synthetic", action="store_true", help="Do not generate synthetic placeholder images when internet images are unavailable")

    def handle(self, *args, **options):
        limit = int(options.get("limit") or 0)
        spin_frames = max(4, int(options.get("spin_frames") or 8))
        force = bool(options.get("force"))
        keep_placeholders = bool(options.get("keep_placeholders"))
        make_filter = (options.get("make") or "").strip()
        model_filter = (options.get("model") or "").strip()
        strict_model = bool(options.get("strict_model"))
        no_synthetic = bool(options.get("no_synthetic"))

        qs = CarListing.objects.select_related("car").prefetch_related("images", "assets").order_by("-created_at")
        if make_filter:
            qs = qs.filter(car__make__iexact=make_filter)
        if model_filter:
            qs = qs.filter(car__model__iexact=model_filter)
        if limit > 0:
            # Apply limit early so we don't pre-scan the entire table when the user asks for a small run.
            qs = qs[:limit]

        if not force:
            incomplete_ids = []
            for lst in qs:
                alts = {((im.alt or "").strip().lower()) for im in lst.images.all()}
                has_exterior = any("exterior" in k and "spin" not in k for k in alts)
                has_interior = any("interior" in k and "spin" not in k for k in alts)
                has_spin_ext = any("spin exterior" in k for k in alts)
                has_spin_int = any("spin interior" in k for k in alts)
                asset_kinds = {a.kind for a in lst.assets.all()}
                has_pano_ext = CarListingAsset.Kind.PANORAMA_EXTERIOR in asset_kinds
                has_pano_int = CarListingAsset.Kind.PANORAMA_INTERIOR in asset_kinds
                if not (has_exterior and has_interior and has_spin_ext and has_spin_int and has_pano_ext and has_pano_int):
                    incomplete_ids.append(lst.pk)
            qs = CarListing.objects.select_related("car").prefetch_related("images", "assets").filter(pk__in=incomplete_ids).order_by("-created_at")

        listings = list(qs)
        total = len(listings)

        combos_cache: dict[tuple[str, str], dict[str, object]] = {}

        updated = 0
        skipped = 0
        failed = 0

        for idx, lst in enumerate(listings, start=1):
            self.stdout.write(f"[{idx}/{total}] Listing #{lst.pk}: checking media")
            make = (lst.car.make or "").strip()
            model = (lst.car.model or "").strip()

            existing_alts = {((im.alt or "").strip().lower()): im for im in lst.images.all()}
            placeholder_images = [im for im in lst.images.all() if str(getattr(im.image, "name", "")).lower().endswith(".svg")]
            has_exterior = any("exterior" in k and "spin" not in k for k in existing_alts.keys())
            has_interior = any("interior" in k and "spin" not in k for k in existing_alts.keys())
            has_spin_ext = any("spin exterior" in k for k in existing_alts.keys())
            has_spin_int = any("spin interior" in k for k in existing_alts.keys())
            asset_kinds = {a.kind for a in lst.assets.all()}
            has_pano_ext = CarListingAsset.Kind.PANORAMA_EXTERIOR in asset_kinds
            has_pano_int = CarListingAsset.Kind.PANORAMA_INTERIOR in asset_kinds

            if (not force) and has_exterior and has_interior and has_spin_ext and has_spin_int and has_pano_ext and has_pano_int:
                skipped += 1
                continue

            key = (make, model)
            media = combos_cache.get(key)

            if media is None:
                model_query = re.sub(r"\s*\(.*?\)\s*", " ", model).strip()
                q_ext = f"{make} {model_query}"
                q_int = f"{make} {model_query} interior"
                make_tokens = _tokens(make)
                model_tokens = _tokens(model)
                if strict_model:
                    ext_raw = _fetch_internet_image(q_ext, required_tokens=make_tokens, preferred_tokens=model_tokens + ["front", "side", "exterior"])
                    int_raw = _fetch_internet_image(q_int, required_tokens=make_tokens, preferred_tokens=model_tokens + ["interior", "dashboard", "cabin"])
                    if not int_raw and ext_raw:
                        # Keep model consistency over forcing unrelated "interior" results.
                        int_raw = ext_raw
                else:
                    ext_raw = _fetch_internet_image(q_ext, required_tokens=make_tokens, preferred_tokens=model_tokens + ["front", "side", "exterior"])
                    int_raw = _fetch_internet_image(q_int, required_tokens=make_tokens, preferred_tokens=model_tokens + ["interior", "dashboard", "cabin"])

                if not strict_model:
                    if not ext_raw:
                        ext_raw = _fetch_internet_image(f"{make} exterior", required_tokens=make_tokens, preferred_tokens=model_tokens + ["front", "side"])
                    if not int_raw:
                        int_raw = _fetch_internet_image(f"{make} {model} dashboard", required_tokens=make_tokens, preferred_tokens=model_tokens + ["interior", "dashboard", "cockpit"])
                    if not int_raw:
                        int_raw = _fetch_internet_image(f"{model} interior", preferred_tokens=make_tokens + model_tokens + ["interior", "dashboard", "cabin"])

                if not strict_model:
                    if not ext_raw:
                        ext_raw = _fetch_unsplash_image(f"{make} {model} exterior", size="1600x900")
                    if not int_raw:
                        int_raw = _fetch_unsplash_image(f"{make} {model} interior", size="1600x900")
                    if not int_raw:
                        int_raw = _fetch_unsplash_image(f"{model} interior", size="1600x900")

                if (not strict_model) and (not no_synthetic):
                    if not ext_raw:
                        ext_raw = _synthetic_image(make, model, "Exterior")
                    if not int_raw:
                        int_raw = _synthetic_image(make, model, "Interior")

                if not ext_raw or not int_raw:
                    failed += 1
                    self.stdout.write(f"[{idx}/{total}] Listing #{lst.pk}: skipped (no strict model-accurate match)")
                    continue

                ext_img = _open_rgb(ext_raw)
                int_img = _open_rgb(int_raw)

                ext_16x9 = _center_crop_ratio(ext_img, 16, 9, 1600, 900)
                int_16x9 = _center_crop_ratio(int_img, 16, 9, 1600, 900)
                pano_ext_2x1 = _center_crop_ratio(ext_img, 2, 1, 2000, 1000)
                pano_int_2x1 = _center_crop_ratio(int_img, 2, 1, 2000, 1000)

                ext_spin = _spin_frames_from_base(ext_img, frames=spin_frames, out_w=1280, out_h=720)
                int_spin = _spin_frames_from_base(int_img, frames=spin_frames, out_w=1280, out_h=720)

                folder = f"{_slug(make)}-{_slug(model)}"
                ext_main_name = _save_shared_file(folder, "exterior_main.jpg", _to_jpg_bytes(ext_16x9))
                int_main_name = _save_shared_file(folder, "interior_main.jpg", _to_jpg_bytes(int_16x9))
                pano_ext_name = _save_shared_file(folder, "pano_exterior_2x1.jpg", _to_jpg_bytes(pano_ext_2x1))
                pano_int_name = _save_shared_file(folder, "pano_interior_2x1.jpg", _to_jpg_bytes(pano_int_2x1))

                ext_spin_names = []
                int_spin_names = []
                for i, frame in enumerate(ext_spin, start=1):
                    ext_spin_names.append(_save_shared_file(folder, f"spin_exterior_{i:02d}.jpg", frame))
                for i, frame in enumerate(int_spin, start=1):
                    int_spin_names.append(_save_shared_file(folder, f"spin_interior_{i:02d}.jpg", frame))

                media = {
                    "ext_main": ext_main_name,
                    "int_main": int_main_name,
                    "pano_ext": pano_ext_name,
                    "pano_int": pano_int_name,
                    "spin_ext": ext_spin_names,
                    "spin_int": int_spin_names,
                }
                combos_cache[key] = media

            # Attach media references to this listing
            if not keep_placeholders and placeholder_images:
                for im in placeholder_images:
                    im.delete()

            if force or not has_exterior:
                CarListingImage.objects.create(listing=lst, image=str(media["ext_main"]), alt="Exterior Main")
            if force or not has_interior:
                CarListingImage.objects.create(listing=lst, image=str(media["int_main"]), alt="Interior Main")

            if force or not has_spin_ext:
                for i, n in enumerate(media["spin_ext"], start=1):
                    CarListingImage.objects.create(listing=lst, image=str(n), alt=f"Spin Exterior {i:02d}")

            if force or not has_spin_int:
                for i, n in enumerate(media["spin_int"], start=1):
                    CarListingImage.objects.create(listing=lst, image=str(n), alt=f"Spin Interior {i:02d}")

            if force or not has_pano_ext:
                CarListingAsset.objects.create(
                    listing=lst,
                    asset=str(media["pano_ext"]),
                    kind=CarListingAsset.Kind.PANORAMA_EXTERIOR,
                    label="Exterior 360 2:1",
                )
            if force or not has_pano_int:
                CarListingAsset.objects.create(
                    listing=lst,
                    asset=str(media["pano_int"]),
                    kind=CarListingAsset.Kind.PANORAMA_INTERIOR,
                    label="Interior 360 2:1",
                )

            updated += 1
            self.stdout.write(f"[{idx}/{total}] Listing #{lst.pk}: media attached")

        self.stdout.write(self.style.SUCCESS("Internet media enrichment completed."))
        self.stdout.write(f"Updated listings: {updated}")
        self.stdout.write(f"Skipped listings: {skipped}")
        self.stdout.write(f"Failed listings (internet fetch issue): {failed}")
