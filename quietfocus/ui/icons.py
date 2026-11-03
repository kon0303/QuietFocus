"""Icon extraction and vector-ish UI images."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging
import os
import zlib
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageTk

from ..paths import resource_path

log = logging.getLogger(__name__)

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", w.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", w.DWORD),
        ("szDisplayName", w.WCHAR * 260),
        ("szTypeName", w.WCHAR * 80),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


_shell32.SHGetFileInfoW.argtypes = [
    w.LPCWSTR,
    w.DWORD,
    ctypes.POINTER(SHFILEINFOW),
    w.UINT,
    w.UINT,
]
_shell32.SHGetFileInfoW.restype = ctypes.c_void_p
_user32.DrawIconEx.argtypes = [
    w.HDC,
    ctypes.c_int,
    ctypes.c_int,
    w.HICON,
    ctypes.c_int,
    ctypes.c_int,
    w.UINT,
    w.HBRUSH,
    w.UINT,
]
_user32.DrawIconEx.restype = w.BOOL
_user32.GetDC.argtypes = [w.HWND]
_user32.GetDC.restype = w.HDC
_user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
_user32.DestroyIcon.argtypes = [w.HICON]
_gdi32.CreateCompatibleDC.argtypes = [w.HDC]
_gdi32.CreateCompatibleDC.restype = w.HDC
_gdi32.CreateDIBSection.argtypes = [
    w.HDC,
    ctypes.POINTER(BITMAPINFO),
    w.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    w.HANDLE,
    w.DWORD,
]
_gdi32.CreateDIBSection.restype = w.HBITMAP
_gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
_gdi32.SelectObject.restype = w.HGDIOBJ
_gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [w.HDC]
_gdi32.PatBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.DWORD]

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
BLACKNESS = 0x00000042
DI_NORMAL = 0x0003


@lru_cache(maxsize=256)
def _extract_pil(path: str, size: int) -> Image.Image | None:
    if not path or not os.path.isfile(path):
        return None
    info = SHFILEINFOW()
    result = _shell32.SHGetFileInfoW(
        path,
        0,
        ctypes.byref(info),
        ctypes.sizeof(info),
        SHGFI_ICON | SHGFI_LARGEICON,
    )
    if not result or not info.hIcon:
        return None
    hdc_screen = None
    hdc = None
    hbitmap = None
    old = None
    try:
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(header)
        header.biWidth = size
        header.biHeight = -size
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        bmi = BITMAPINFO()
        bmi.bmiHeader = header
        hdc_screen = _user32.GetDC(None)
        hdc = _gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        hbitmap = _gdi32.CreateDIBSection(
            hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
        )
        if not hbitmap or not bits.value:
            return None
        old = _gdi32.SelectObject(hdc, hbitmap)
        _gdi32.PatBlt(hdc, 0, 0, size, size, BLACKNESS)
        if not _user32.DrawIconEx(hdc, 0, 0, info.hIcon, size, size, 0, None, DI_NORMAL):
            return None
        raw = ctypes.string_at(bits.value, size * size * 4)
        image = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1).copy()
        if image.getextrema()[3][1] == 0:
            # Legacy icon without an alpha channel: treat near-black pixels as
            # transparent and keep the rest opaque.
            rgba = image.convert("RGBA")
            pixels = rgba.load()
            for y in range(size):
                for x in range(size):
                    r, g, b, _ = pixels[x, y]
                    if r + g + b < 12:
                        pixels[x, y] = (0, 0, 0, 0)
                    else:
                        pixels[x, y] = (r, g, b, 255)
            image = rgba
        return image
    except Exception as exc:
        log.debug("Could not extract icon from %s: %s", path, exc)
        return None
    finally:
        try:
            if hdc is not None and old is not None:
                _gdi32.SelectObject(hdc, old)
            if hbitmap:
                _gdi32.DeleteObject(hbitmap)
            if hdc:
                _gdi32.DeleteDC(hdc)
            if hdc_screen:
                _user32.ReleaseDC(None, hdc_screen)
        finally:
            if info.hIcon:
                _user32.DestroyIcon(info.hIcon)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("msyhbd.ttc", "msyh.ttc", "segoeuib.ttf", "arialbd.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


_LETTER_COLORS = (
    (14, 159, 138),
    (49, 121, 176),
    (142, 101, 180),
    (193, 121, 53),
    (62, 139, 106),
    (174, 83, 111),
    (90, 110, 180),
    (150, 110, 60),
)


def _letter_avatar(name: str, exe_name: str, size: int) -> Image.Image:
    seed = (name or exe_name or "?").encode("utf-8", "ignore")
    color = _LETTER_COLORS[zlib.crc32(seed) % len(_LETTER_COLORS)]
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(4, int(size * 0.28))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=color)
    letter = (name or os.path.splitext(exe_name)[0] or "?").strip()[:1].upper()
    try:
        font = _font(max(9, int(size * 0.48)))
        bbox = draw.textbbox((0, 0), letter, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - size * 0.02),
            letter,
            font=font,
            fill=(255, 255, 255, 255),
        )
    except Exception:
        pass
    return image


def _check_image(scale: float, checked: bool) -> Image.Image:
    size = max(18, round(21 * scale))
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = max(1, round(scale))
    radius = max(5, round(6 * scale))
    box = (inset, inset, size - inset - 1, size - inset - 1)
    width = max(1, round(1.4 * scale))
    if checked:
        draw.rounded_rectangle(box, radius=radius, fill=(14, 159, 138, 255))
        points = [
            (size * 0.28, size * 0.52),
            (size * 0.44, size * 0.68),
            (size * 0.73, size * 0.34),
        ]
        draw.line(points, fill=(255, 255, 255, 255), width=max(2, round(2.1 * scale)), joint="curve")
    else:
        draw.rounded_rectangle(
            box,
            radius=radius,
            fill=(255, 255, 255, 255),
            outline=(199, 212, 206, 255),
            width=width,
        )
    return image


class IconProvider:
    """Caches Tk images for the lifetime of one Tk root."""

    def __init__(self, root, scale: float = 1.0) -> None:
        self.root = root
        self.scale = scale
        self._app_icons: dict[tuple[str, str, str, int], ImageTk.PhotoImage] = {}
        self._checks: dict[bool, ImageTk.PhotoImage] = {}

    def app_icon(
        self,
        exe_path: str,
        exe_name: str,
        name: str,
        size: int | None = None,
    ) -> ImageTk.PhotoImage:
        target = size or max(28, round(30 * self.scale))
        cache_key = (exe_path.casefold(), exe_name.casefold(), name.casefold(), target)
        cached = self._app_icons.get(cache_key)
        if cached is not None:
            return cached
        source_size = max(32, target)
        pil = _extract_pil(exe_path, source_size)
        if pil is None:
            pil = _letter_avatar(name, exe_name, source_size)
        elif pil.size != (target, target):
            pil = pil.resize((target, target), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(pil, master=self.root)
        self._app_icons[cache_key] = photo
        return photo

    def checkbox(self, checked: bool) -> ImageTk.PhotoImage:
        cached = self._checks.get(checked)
        if cached is not None:
            return cached
        pil = _check_image(self.scale, checked)
        photo = ImageTk.PhotoImage(pil, master=self.root)
        self._checks[checked] = photo
        return photo

    def logo(self, size: int | None = None) -> ImageTk.PhotoImage:
        target = size or max(42, round(46 * self.scale))
        path = resource_path("assets", "logo_128.png")
        try:
            image = Image.open(path).convert("RGBA")
        except OSError:
            image = _letter_avatar("静", "", target)
        image = image.resize((target, target), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image, master=self.root)
        self._logo = photo  # keep a reference
        return photo


def tray_image() -> Image.Image:
    path = resource_path("assets", "icon.png")
    try:
        return Image.open(path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    except OSError:
        return _letter_avatar("静", "", 64)
