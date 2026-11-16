"""Export full-resolution face and neck crops into retouch sheets."""
import io
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PIL import Image, ImageCms, ImageOps

OUTPUT = "_face_retouch"
LIMIT = 12000
SHEET_FORMATS = ("jpg", "tif")
DEFAULT_SHEET_FORMAT = "jpg"
NECK_MARGIN = 0.85
DETECTOR_THRESHOLD = 0.45
DETECTION_TILE = 1400
GAP = 16
EXTENSIONS = {".psd", ".tif", ".tiff", ".jpg", ".jpeg"}
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


@dataclass
class Patch:
    path: str
    image_size: tuple
    rect: tuple
    number: int
    file: Path
    x: int = 0
    y: int = 0

    @property
    def size(self):
        x1, y1, x2, y2 = self.rect
        return x2 - x1, y2 - y1


@dataclass
class Shelf:
    y: int
    height: int
    next_x: int = 0


@dataclass
class Sheet:
    shelves: list = field(default_factory=list)
    patches: list = field(default_factory=list)
    width: int = 0
    height: int = 0

    def add(self, patch, shelf):
        width, height = patch.size
        patch.x, patch.y = shelf.next_x, shelf.y
        shelf.next_x += width + GAP
        self.width = max(self.width, patch.x + width)
        self.height = max(self.height, patch.y + height)
        self.patches.append(patch)


def read_image(path):
    if path.suffix.lower() == ".psd":
        try:
            from psd_tools import PSDImage
            from psd_tools.constants import Resource
        except ImportError as exc:
            raise ValueError("Для PSD установите psd-tools в окружение программы.") from exc

        psd = PSDImage.open(path)
        if psd.depth not in (8, 16):
            raise ValueError("PSD: поддерживаются 8 и 16 бит/канал.")
        if not psd.has_preview():
            raise ValueError("PSD: сохраните файл с максимальной совместимостью, чтобы записать композит.")
        image = psd.topil(apply_icc=False)
        profile = psd.image_resources.get_data(Resource.ICC_PROFILE)
        if image is None or image.size != psd.size:
            raise ValueError("PSD: full-size composite unavailable")
    else:
        with Image.open(path) as source:
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("multi-page TIFF is unsupported")
            profile = source.info.get("icc_profile")
            image = ImageOps.exif_transpose(source)
    if image.mode not in ("RGB", "RGBA"):
        raise ValueError(f"expected RGB document, got {image.mode}")
    if image.mode == "RGBA" and image.getchannel("A").getextrema()[0] != 255:
        raise ValueError("transparent composite: provide a visible opaque background")
    image = image.convert("RGB")
    if profile:
        image = ImageCms.profileToProfile(
            image, ImageCms.ImageCmsProfile(io.BytesIO(profile)), SRGB,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode="RGB",
        )
    return image


def tile_starts(length, tile):
    if length <= tile:
        return [0]
    count = math.ceil((length - tile) / (tile * 0.72)) + 1
    return [round(i * (length - tile) / (count - 1)) for i in range(count)]


def intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def duplicate(a, b):
    common = intersection(a, b)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return common >= 0.48 * (area_a + area_b - common)


def detect_faces(image, detector, tile, check_cancel):
    bgr = np.asarray(image)[:, :, ::-1]
    width, height = image.size
    regions = [(0, 0, width, height)]
    if tile and max(width, height) > tile:
        regions.extend((x, y, min(x + tile, width), min(y + tile, height))
                       for y in tile_starts(height, tile)
                       for x in tile_starts(width, tile))
    candidates = []
    for x, y, right, bottom in regions:
        check_cancel()
        rows, _ = detector.detect(np.ascontiguousarray(bgr[y:bottom, x:right]), max_num=0)
        if rows is None:
            continue
        for a, b, c, d, score in rows:
            if not np.isfinite([a, b, c, d, score]).all() or c <= a or d <= b:
                continue
            margin = max(4, min(c - a, d - b) * 0.08)
            if ((x and a <= margin) or (y and b <= margin)
                    or (right < width and c >= right - x - margin)
                    or (bottom < height and d >= bottom - y - margin)):
                continue
            rect = (max(0, x + a), max(0, y + b), min(width, x + c), min(height, y + d))
            if rect[2] > rect[0] and rect[3] > rect[1]:
                candidates.append((float(score), rect))
    faces = []
    for _, rect in sorted(candidates, reverse=True):
        if not any(duplicate(rect, existing) for existing in faces):
            faces.append(rect)
    return sorted(faces, key=lambda rect: (rect[1], rect[0]))


def face_and_neck(box, image_size, neck):
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    side = max(width * 0.32, height * 0.14)
    return (
        max(0, math.floor(x1 - side)), max(0, math.floor(y1 - height * 0.20)),
        min(image_size[0], math.ceil(x2 + side)), min(image_size[1], math.ceil(y2 + height * neck)),
    )


def pack(patches, max_width, max_height, check_cancel):
    sheets = []
    for patch in sorted(patches, key=lambda patch: patch.size[::-1], reverse=True):
        check_cancel()
        width, height = patch.size
        options = [(max_width - shelf.next_x - width, index, shelf.y, sheet, shelf)
                   for index, sheet in enumerate(sheets) for shelf in sheet.shelves
                   if height <= shelf.height and shelf.next_x + width <= max_width]
        if options:
            *_, sheet, shelf = min(options)
        else:
            sheet = next((page for page in sheets if page.height + GAP + height <= max_height), None)
            if sheet is None:
                sheet = Sheet()
                sheets.append(sheet)
            shelf = Shelf(sheet.height + GAP if sheet.shelves else 0, height)
            sheet.shelves.append(shelf)
        sheet.add(patch, shelf)
    return sheets


@dataclass(frozen=True)
class RetouchOptions:
    image_format: str = DEFAULT_SHEET_FORMAT
    neck_margin: float = NECK_MARGIN
    max_width: int = LIMIT
    max_height: int = LIMIT


@dataclass(frozen=True)
class RetouchSummary:
    destination: Path
    photos: int
    patches: int
    sheets: int
    no_faces: int
    overlaps: int
    errors: int


def find_sources(root, check_cancel):
    paths = []
    for directory, folders, filenames in os.walk(root, onerror=_raise_scan_error):
        check_cancel()
        folders[:] = sorted(name for name in folders
                            if name.casefold() != OUTPUT.casefold()
                            and not name.startswith(".face-retouch-"))
        paths.extend(path for name in sorted(filenames)
                     if (path := Path(directory) / name).suffix.lower() in EXTENSIONS)
    return paths


def _raise_scan_error(error):
    raise error


def scan(root, options, spool, detector, progress, check_cancel, log):
    patches = []
    report = ["file\tstatus\tfaces\tdetail"]
    counts = {status: 0 for status in ("ok", "overlap", "no_faces", "error")}
    sources = find_sources(root, check_cancel)
    for index, path in enumerate(sources, 1):
        check_cancel()
        name = path.relative_to(root).as_posix()
        progress(index - 1, len(sources), f"Анализ · {name}")
        status, count, detail = "error", 0, ""
        try:
            image = read_image(path)
        except Exception as exc:
            detail = " ".join(str(exc).split())
        else:
            boxes = detect_faces(image, detector, DETECTION_TILE, check_cancel)
            pending = [
                Patch(name, image.size, face_and_neck(box, image.size, options.neck_margin),
                      number, spool / f"{index}_{number}.tif")
                for number, box in enumerate(boxes, 1)
            ]
            oversized = next((patch for patch in pending if patch.size[0] > options.max_width or patch.size[1] > options.max_height), None)
            if oversized:
                width, height = oversized.size
                detail = (f"Фрагмент {oversized.number}: {width} × {height}, превышен лимит "
                          f"{options.max_width} × {options.max_height} px")
            else:
                overlap = False
                for i, patch in enumerate(pending):
                    check_cancel()
                    image.crop(patch.rect).save(patch.file, compression="tiff_adobe_deflate")
                    overlap |= any(intersection(patch.rect, other.rect) > 0 for other in pending[:i])
                patches.extend(pending)
                count = len(pending)
                status = "overlap" if overlap else "ok" if pending else "no_faces"
        if status != "ok":
            log(f"Листы ретуши: {name} — {status} {detail}".rstrip())
        counts[status] += 1
        report.append(f"{name}\t{status}\t{count}\t{detail}")
    return patches, report, counts, len(sources)


def write_sheets(sheets, directory, image_format, progress, check_cancel):
    manifest = ["FACE_RETOUCH_SHEETS\t1"]
    for index, sheet in enumerate(sheets, 1):
        filename = f"faces_{index:03d}.{image_format}"
        check_cancel()
        progress(index - 1, len(sheets), f"Запись · {filename}")
        with Image.new("RGB", (sheet.width, sheet.height), (112, 112, 112)) as canvas:
            for patch in sheet.patches:
                check_cancel()
                with Image.open(patch.file) as crop:
                    canvas.paste(crop, (patch.x, patch.y))
                row = (quote(patch.path, safe="/"), *patch.image_size, patch.number, *patch.rect,
                       filename, sheet.width, sheet.height, patch.x, patch.y)
                manifest.append("\t".join(str(value) for value in row))
            options = {"quality": 100, "subsampling": 0} if image_format == "jpg" else {"compression": "tiff_adobe_deflate"}
            canvas.save(directory / filename, icc_profile=SRGB.tobytes(), **options)
        progress(index, len(sheets), f"Записан {filename}")
    (directory / "face-map.tsv").write_text("\n".join(manifest) + "\n", encoding="utf-8")


def validate_destination(root):
    if not root.is_dir():
        raise ValueError("Папка фотографий не существует.")
    output = root / OUTPUT
    if output.exists() or output.is_symlink():
        raise FileExistsError(
            f"Папка {output} уже существует. Переместите её за пределы съёмки перед повторным экспортом."
        )
    return output


def validate_sheet_size(width, height):
    if not (type(width) is int and type(height) is int and
            1 <= width <= LIMIT and 1 <= height <= LIMIT):
        raise ValueError(f"Ширина и высота листа должны быть от 1 до {LIMIT} px.")


def export_retouch(root, options, detector, progress, check_cancel, log):
    if options.image_format not in SHEET_FORMATS:
        raise ValueError("Формат листа должен быть JPG или TIF.")
    validate_sheet_size(options.max_width, options.max_height)
    output = validate_destination(root)
    with tempfile.TemporaryDirectory(prefix=".face-retouch-", dir=root) as temporary:
        staging = Path(temporary) / "output"
        staging.mkdir()
        progress(0, 0, "Поиск фотографий…")
        patches, report, counts, photo_count = scan(
            root, options, Path(temporary), detector, progress, check_cancel, log
        )
        progress(0, 0, "Раскладка фрагментов…")
        sheets = pack(patches, options.max_width, options.max_height, check_cancel)
        write_sheets(sheets, staging, options.image_format, progress, check_cancel)
        (staging / "scan-report.tsv").write_text("\n".join(report) + "\n", encoding="utf-8-sig")
        check_cancel()
        validate_destination(root)
        staging.rename(output)
    return RetouchSummary(output, photo_count, len(patches), len(sheets),
                          counts["no_faces"], counts["overlap"], counts["error"])
