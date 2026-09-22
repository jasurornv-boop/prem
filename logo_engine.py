"""
logo_engine.py — Logo/Text emoji generatsiya "dvigateli".

tgs_make_bot loyihasidan ajratib olingan, faqat sof logika: SVG parsing,
matndan SVG yasash, Lottie (.tgs) rangini o'zgartirish va logo joyiga
SVG/matnni joylashtirish. Telegram bot handlerlari bu yerda yo'q — ular
bot.py da.
"""

import copy
import gzip
import io
import json
import math
import os
import re
import colorsys
import xml.etree.ElementTree as ET

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_LOGO_COLOR = "#FFFFFF"   # logo har doim shu rangda chiziladi (agar logo rangi tanlanmasa)
SIZE_MIN_PERCENT = 30
SIZE_MAX_PERCENT = 300
DEFAULT_SIZE_PERCENT = 135  # har doim shu o'lchamda boshlanadi

FONT_OPTIONS = {
    "sans": ("Standart (Sans)", os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")),
    "classic": ("Klassik", os.path.join(BASE_DIR, "fonts", "LiberationSans-Bold.ttf")),
    "modern": ("Zamonaviy", os.path.join(BASE_DIR, "fonts", "Outfit-Bold.ttf")),
    "serif": ("𝐒𝐞𝐫𝐢𝐟", os.path.join(BASE_DIR, "fonts", "IBMPlexSerif-Bold.ttf")),
    "mono": ("𝙼𝚘𝚗𝚘", os.path.join(BASE_DIR, "fonts", "JetBrainsMono-Bold.ttf")),
}

FALLBACK_FONT = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")
TEXT_FONT_PATH = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")  # matndan logo yasashda standart shrift


def font_choice_kb():
    items = list(FONT_OPTIONS.items())
    rows = []
    for i in range(0, len(items), 2):
        pair = items[i:i + 2]
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"font:{key}")
            for key, (label, _path) in pair
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================================
# 3) SVG -> LOTTIE BEZIER KONVERTORI (tashqi kutubxonasiz)
# ============================================================================

CMD_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")

# "A"/"a" (elliptik yoy) argumentlari orasidagi flag'lar (large-arc-flag,
# sweep-flag) SVG spetsifikatsiyasiga ko'ra ajratuvchisiz ham yozilishi mumkin
# (masalan "A2.5,2.5,0,011,5,5" — "0","1","1" flag'lar orasida vergul yo'q).
# Buni hisobga olmasa, arc'dan keyingi barcha sonlar noto'g'ri o'qiladi va
# natijada shaklning (yoki harfning) qolgan qismi butunlay yo'qolib/buzilib
# ketadi — SVG'dagi shakllar/harflar yo'qolib qolishining asosiy sababi shu edi.
_ARC_SET_RE = re.compile(
    r'\s*,?\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)'
    r'\s*,?\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)'
    r'\s*,?\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)'
    r'\s*,?\s*([01])'
    r'\s*,?\s*([01])'
    r'\s*,?\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)'
    r'\s*,?\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)'
)
_ARC_BLOCK_RE = re.compile(r'([Aa])([^MmLlHhVvCcSsQqTtAaZz]*)')

def _normalize_arc_flags(d):
    """'A'/'a' argumentlarini flag ajratuvchisiz yozuvlardan ham xavfsiz
    o'qish uchun, har bir arc argument to'plamini aniq bo'shliqlar bilan
    qayta yozadi (tokenizatsiyadan oldin)."""
    def repl(m):
        cmd, rest = m.group(1), m.group(2)
        parts = []
        pos = 0
        while True:
            am = _ARC_SET_RE.match(rest, pos)
            if not am:
                break
            parts.append(" ".join(am.groups()))
            pos = am.end()
        return cmd + " " + " ".join(parts) + " "
    return _ARC_BLOCK_RE.sub(repl, d)


def _svg_tokenize(d):
    d = _normalize_arc_flags(d)
    tokens = []
    for m in CMD_RE.finditer(d):
        if m.group(1):
            tokens.append(m.group(1))
        else:
            tokens.append(float(m.group(2)))
    return tokens


def _arc_to_bezier_segments(x0, y0, rx, ry, x_axis_rotation, large_arc_flag, sweep_flag, x, y):
    """SVG elliptik yoy (A/a) komandasini bitta yoki bir nechta kub Bezier
    segmentiga aylantiradi (SVG spec F.6 — endpoint->center parametrizatsiya).
    Har bir segment (control1, control2, end_x, end_y) qaytaradi."""
    if rx == 0 or ry == 0 or (x0 == x and y0 == y):
        return [((x0, y0), (x, y), x, y)]  # degenerativ holat -> to'g'ri chiziq

    rx = abs(rx); ry = abs(ry)
    phi = math.radians(x_axis_rotation % 360)
    cosphi, sinphi = math.cos(phi), math.sin(phi)

    dx2 = (x0 - x) / 2.0
    dy2 = (y0 - y) / 2.0
    x1p = cosphi * dx2 + sinphi * dy2
    y1p = -sinphi * dx2 + cosphi * dy2

    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s; ry *= s

    sign = -1.0 if large_arc_flag == sweep_flag else 1.0
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    co = sign * math.sqrt(max(num, 0.0) / den) if den != 0 else 0.0
    cxp = co * (rx * y1p / ry)
    cyp = co * (-ry * x1p / rx)

    cx_ = cosphi * cxp - sinphi * cyp + (x0 + x) / 2.0
    cy_ = sinphi * cxp + cosphi * cyp + (y0 + y) / 2.0

    def _ang(ux, uy, vx, vy):
        len_ = math.sqrt(ux ** 2 + uy ** 2) * math.sqrt(vx ** 2 + vy ** 2)
        a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / len_))) if len_ != 0 else 0.0
        return -a if (ux * vy - uy * vx) < 0 else a

    theta1 = _ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)

    if not sweep_flag and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep_flag and dtheta < 0:
        dtheta += 2 * math.pi

    n_segments = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2))))
    delta = dtheta / n_segments
    t = 4.0 / 3.0 * math.tan(delta / 4.0)

    def _to_world(px, py):
        return (
            cosphi * (px * rx) - sinphi * (py * ry) + cx_,
            sinphi * (px * rx) + cosphi * (py * ry) + cy_,
        )

    segments = []
    theta = theta1
    for _ in range(n_segments):
        theta2 = theta + delta
        cos1, sin1 = math.cos(theta), math.sin(theta)
        cos2, sin2 = math.cos(theta2), math.sin(theta2)
        c1 = _to_world(cos1 - t * sin1, sin1 + t * cos1)
        c2 = _to_world(cos2 + t * sin2, sin2 - t * cos2)
        pe = _to_world(cos2, sin2)
        segments.append((c1, c2, pe[0], pe[1]))
        theta = theta2

    return segments


def _svg_parse_path(d):
    tokens = _svg_tokenize(d)
    i = 0
    n = len(tokens)
    subpaths = []
    cur = None
    cx = cy = 0.0
    start_x = start_y = 0.0
    last_cmd = None
    last_ctrl = None

    def new_subpath(x, y):
        nonlocal cur
        cur = {"v": [[x, y]], "out": [[0, 0]], "in_next": [[0, 0]], "closed": False}

    def add_vertex(x, y, out_of_prev=(0, 0), in_of_new=(0, 0)):
        cur["out"][-1] = list(out_of_prev)
        cur["v"].append([x, y])
        cur["out"].append([0, 0])
        cur["in_next"].append(list(in_of_new))

    while i < n:
        tok = tokens[i]
        if isinstance(tok, str):
            cmd = tok
            i += 1
        else:
            cmd = last_cmd
        if cmd is None:
            break
        upper = cmd.upper()
        rel = cmd.islower()

        if upper == "M":
            x, y = tokens[i], tokens[i + 1]; i += 2
            if rel and cur is not None:
                x += cx; y += cy
            cx, cy = x, y
            start_x, start_y = x, y
            if cur is not None:
                subpaths.append(cur)
            new_subpath(x, y)
            last_cmd = "l" if rel else "L"

        elif upper == "L":
            x, y = tokens[i], tokens[i + 1]; i += 2
            if rel:
                x += cx; y += cy
            add_vertex(x, y); cx, cy = x, y
            last_cmd = cmd

        elif upper == "H":
            x = tokens[i]; i += 1
            if rel:
                x += cx
            add_vertex(x, cy); cx = x
            last_cmd = cmd

        elif upper == "V":
            y = tokens[i]; i += 1
            if rel:
                y += cy
            add_vertex(cx, y); cy = y
            last_cmd = cmd

        elif upper == "C":
            x1, y1, x2, y2, x, y = tokens[i:i + 6]; i += 6
            if rel:
                x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
            add_vertex(x, y, out_of_prev=(x1 - cx, y1 - cy), in_of_new=(x2 - x, y2 - y))
            cx, cy = x, y
            last_ctrl = (x2, y2)
            last_cmd = cmd

        elif upper == "S":
            x2, y2, x, y = tokens[i:i + 4]; i += 4
            if rel:
                x2 += cx; y2 += cy; x += cx; y += cy
            if last_ctrl is not None and last_cmd and last_cmd.upper() in ("C", "S"):
                x1 = 2 * cx - last_ctrl[0]; y1 = 2 * cy - last_ctrl[1]
            else:
                x1, y1 = cx, cy
            add_vertex(x, y, out_of_prev=(x1 - cx, y1 - cy), in_of_new=(x2 - x, y2 - y))
            cx, cy = x, y
            last_ctrl = (x2, y2)
            last_cmd = cmd

        elif upper == "Q":
            x1, y1, x, y = tokens[i:i + 4]; i += 4
            if rel:
                x1 += cx; y1 += cy; x += cx; y += cy
            c1x = cx + 2 / 3 * (x1 - cx); c1y = cy + 2 / 3 * (y1 - cy)
            c2x = x + 2 / 3 * (x1 - x); c2y = y + 2 / 3 * (y1 - y)
            add_vertex(x, y, out_of_prev=(c1x - cx, c1y - cy), in_of_new=(c2x - x, c2y - y))
            cx, cy = x, y
            last_ctrl = (x1, y1)
            last_cmd = cmd

        elif upper == "T":
            x, y = tokens[i], tokens[i + 1]; i += 2
            if rel:
                x += cx; y += cy
            if last_ctrl is not None and last_cmd and last_cmd.upper() in ("Q", "T"):
                x1 = 2 * cx - last_ctrl[0]; y1 = 2 * cy - last_ctrl[1]
            else:
                x1, y1 = cx, cy
            c1x = cx + 2 / 3 * (x1 - cx); c1y = cy + 2 / 3 * (y1 - cy)
            c2x = x + 2 / 3 * (x1 - x); c2y = y + 2 / 3 * (y1 - y)
            add_vertex(x, y, out_of_prev=(c1x - cx, c1y - cy), in_of_new=(c2x - x, c2y - y))
            cx, cy = x, y
            last_ctrl = (x1, y1)
            last_cmd = cmd

        elif upper == "A":
            rx, ry, xrot, large_arc, sweep, x, y = tokens[i:i + 7]; i += 7
            if rel:
                x += cx; y += cy
            segs = _arc_to_bezier_segments(cx, cy, rx, ry, xrot, bool(large_arc), bool(sweep), x, y)
            for c1, c2, ex, ey in segs:
                add_vertex(ex, ey, out_of_prev=(c1[0] - cx, c1[1] - cy), in_of_new=(c2[0] - ex, c2[1] - ey))
                cx, cy = ex, ey
            last_cmd = cmd
            last_ctrl = None

        elif upper == "Z":
            if cur is not None:
                cur["closed"] = True
                cx, cy = start_x, start_y
            last_cmd = cmd
            last_ctrl = None
        else:
            i += 1

    if cur is not None:
        subpaths.append(cur)

    result = []
    for sp in subpaths:
        v = sp["v"]; out = sp["out"]; in_next = sp["in_next"]; closed = sp["closed"]
        if closed and len(v) > 1 and v[0] == v[-1]:
            v = v[:-1]; out = out[:-1]
            i_arr = [in_next[0]] + in_next[1:-1]
        else:
            i_arr = in_next[:len(v)]
            out = out[:len(v)]
        result.append({"closed": closed, "v": v, "i": i_arr, "o": out})
    return result


_IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mat_mul(m1, m2):
    """m1 * m2 — ikkala 2x3 affin matritsani birlashtiradi (avval m2, keyin m1 qo'llanadi)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform_attr(s):
    """SVG 'transform' atributini (translate/scale/matrix/rotate/skewX/skewY,
    bir nechtasi ketma-ket bo'lishi mumkin) yagona 2x3 affin matritsaga aylantiradi."""
    result = _IDENTITY_MATRIX
    if not s:
        return result
    for m in re.finditer(r'([a-zA-Z]+)\s*\(([^)]*)\)', s):
        name = m.group(1)
        nums = [float(x) for x in re.findall(r'-?\d*\.?\d+(?:[eE][-+]?\d+)?', m.group(2))]
        if name == "translate":
            tx = nums[0] if len(nums) > 0 else 0.0
            ty = nums[1] if len(nums) > 1 else 0.0
            cur = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale":
            sx = nums[0] if len(nums) > 0 else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            cur = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "matrix" and len(nums) >= 6:
            cur = tuple(nums[:6])
        elif name == "rotate" and nums:
            deg = nums[0]
            rad = math.radians(deg)
            cosr, sinr = math.cos(rad), math.sin(rad)
            rot = (cosr, sinr, -sinr, cosr, 0.0, 0.0)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                cur = _mat_mul(_mat_mul((1.0, 0.0, 0.0, 1.0, cx, cy), rot), (1.0, 0.0, 0.0, 1.0, -cx, -cy))
            else:
                cur = rot
        elif name == "skewX" and nums:
            cur = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and nums:
            cur = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = _mat_mul(result, cur)
    return result


def _apply_matrix_to_subpath(sp, m):
    a, b, c, d, e, f = m

    def tp(pt):
        x, y = pt
        return [a * x + c * y + e, b * x + d * y + f]

    def tv(vec):
        x, y = vec
        return [a * x + c * y, b * x + d * y]

    return {
        "closed": sp["closed"],
        "v": [tp(p) for p in sp["v"]],
        "i": [tv(p) for p in sp["i"]],
        "o": [tv(p) for p in sp["o"]],
    }


def _rect_to_subpath(x, y, w, h):
    v = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    z = [0, 0]
    return {"closed": True, "v": v, "i": [z, z, z, z], "o": [z, z, z, z]}


def _ellipse_to_subpath(cx, cy, rx, ry):
    k = 0.5522847498  # aylanani 4 ta Bezier bilan taxminlash konstantasi
    v = [[cx + rx, cy], [cx, cy + ry], [cx - rx, cy], [cx, cy - ry]]
    out = [[0, ry * k], [-rx * k, 0], [0, -ry * k], [rx * k, 0]]
    inn = [[0, -ry * k], [rx * k, 0], [0, ry * k], [-rx * k, 0]]
    return {"closed": True, "v": v, "i": inn, "o": out}


def _points_to_subpath(points_str, closed):
    nums = [float(x) for x in re.findall(r'-?\d*\.?\d+(?:[eE][-+]?\d+)?', points_str)]
    v = [[nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)]
    z = [0, 0]
    return {"closed": closed, "v": v, "i": [z] * len(v), "o": [z] * len(v)}


def _strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


# ---------- SVG'dagi ASL ranglarni (fill) o'qish — ko'p rangli logolarni saqlab qolish uchun ----------

_NAMED_SVG_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "lime": "#00ff00", "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500",
    "purple": "#800080", "pink": "#ffc0cb", "gray": "#808080", "grey": "#808080",
    "cyan": "#00ffff", "aqua": "#00ffff", "magenta": "#ff00ff", "fuchsia": "#ff00ff",
    "brown": "#a52a2a", "navy": "#000080", "teal": "#008080", "gold": "#ffd700",
    "silver": "#c0c0c0", "maroon": "#800000", "olive": "#808000", "indigo": "#4b0082",
    "violet": "#ee82ee", "darkred": "#8b0000", "darkgreen": "#006400", "darkblue": "#00008b",
    "skyblue": "#87ceeb", "lightblue": "#add8e6", "crimson": "#dc143c", "salmon": "#fa8072",
}


def _parse_css_color(value):
    """'#rgb' / '#rrggbb' / 'rgb(r,g,b)' / nomli rang (red, green...) ni '#rrggbb'ga
    aylantiradi. 'none'/'transparent' yoki tushunarsiz qiymat uchun None qaytaradi."""
    if not value:
        return None
    v = value.strip().lower()
    if v in ("none", "transparent", ""):
        return None
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6 and re.fullmatch(r"[0-9a-f]{6}", h):
            return "#" + h
        return None
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v)
    if m:
        r, g, b = (max(0, min(255, int(x))) for x in m.groups())
        return "#%02x%02x%02x" % (r, g, b)
    return _NAMED_SVG_COLORS.get(v)


def _elem_fill_color(elem, inherited):
    """Elementning fill rangini aniqlaydi: style="fill:..." > fill="..." > meros (inherited).
    Aniq 'none'/'transparent' bo'lsa — shaffof (None) deb qaytaradi (rang o'chadi)."""
    style = elem.attrib.get("style", "")
    if style:
        m = re.search(r"fill\s*:\s*([^;]+)", style)
        if m:
            raw = m.group(1).strip().lower()
            if raw in ("none", "transparent"):
                return None
            parsed = _parse_css_color(raw)
            if parsed:
                return parsed
    fill_attr = elem.attrib.get("fill")
    if fill_attr:
        raw = fill_attr.strip().lower()
        if raw in ("none", "transparent"):
            return None
        parsed = _parse_css_color(raw)
        if parsed:
            return parsed
    return inherited


def _walk_svg_element(elem, parent_matrix, out_subpaths, parent_fill=None):
    tag = _strip_ns(elem.tag)
    local_m = _parse_transform_attr(elem.attrib.get("transform", ""))
    m = _mat_mul(parent_matrix, local_m)
    current_fill = _elem_fill_color(elem, parent_fill)

    try:
        if tag == "path" and elem.attrib.get("d"):
            for sp in _svg_parse_path(elem.attrib["d"]):
                sp2 = _apply_matrix_to_subpath(sp, m)
                sp2["fill"] = current_fill
                out_subpaths.append(sp2)
        elif tag == "rect" and "width" in elem.attrib and "height" in elem.attrib:
            x = float(elem.attrib.get("x", 0)); y = float(elem.attrib.get("y", 0))
            w = float(elem.attrib["width"]); h = float(elem.attrib["height"])
            sp2 = _apply_matrix_to_subpath(_rect_to_subpath(x, y, w, h), m)
            sp2["fill"] = current_fill
            out_subpaths.append(sp2)
        elif tag == "circle":
            cx = float(elem.attrib.get("cx", 0)); cy = float(elem.attrib.get("cy", 0))
            r = float(elem.attrib.get("r", 0))
            if r > 0:
                sp2 = _apply_matrix_to_subpath(_ellipse_to_subpath(cx, cy, r, r), m)
                sp2["fill"] = current_fill
                out_subpaths.append(sp2)
        elif tag == "ellipse":
            cx = float(elem.attrib.get("cx", 0)); cy = float(elem.attrib.get("cy", 0))
            rx = float(elem.attrib.get("rx", 0)); ry = float(elem.attrib.get("ry", 0))
            if rx > 0 and ry > 0:
                sp2 = _apply_matrix_to_subpath(_ellipse_to_subpath(cx, cy, rx, ry), m)
                sp2["fill"] = current_fill
                out_subpaths.append(sp2)
        elif tag in ("polygon", "polyline") and elem.attrib.get("points"):
            sp = _points_to_subpath(elem.attrib["points"], closed=(tag == "polygon"))
            if len(sp["v"]) >= 2:
                sp2 = _apply_matrix_to_subpath(sp, m)
                sp2["fill"] = current_fill
                out_subpaths.append(sp2)
    except Exception:
        pass  # bitta shakl parslanmasa ham, qolganlarini yo'qotmaymiz

    for child in elem:
        _walk_svg_element(child, m, out_subpaths, current_fill)


def svg_parse_paths(svg_text):
    vb_match = re.search(r'viewBox\s*=\s*"([-\d.\s]+)"', svg_text)
    if vb_match:
        viewbox = tuple(float(x) for x in vb_match.group(1).split())
    else:
        w_match = re.search(r'width\s*=\s*"([\d.]+)', svg_text)
        h_match = re.search(r'height\s*=\s*"([\d.]+)', svg_text)
        w = float(w_match.group(1)) if w_match else 512.0
        h = float(h_match.group(1)) if h_match else 512.0
        viewbox = (0, 0, w, h)

    all_subpaths = []
    try:
        root = ET.fromstring(svg_text)
        _walk_svg_element(root, _IDENTITY_MATRIX, all_subpaths, parent_fill=None)
    except ET.ParseError:
        pass

    if not all_subpaths:
        # XML sifatida o'qib bo'lmasa (masalan noto'g'ri belgilar), eski oddiy usulga
        # tushamiz — <g transform> hisobga olinmaydi, lekin hech narsadan ko'ra yaxshi.
        for path_match in re.finditer(r'<path\b[^>]*\bd\s*=\s*"([^"]+)"', svg_text):
            try:
                all_subpaths.extend(_svg_parse_path(path_match.group(1)))
            except Exception:
                continue

    if not all_subpaths:
        raise ValueError("SVG ichida <path>/<rect>/<circle>/<polygon> topilmadi yoki tahlil qilib bo'lmadi")
    return all_subpaths, viewbox


_TEXT_FONT_CACHE = {}


def _load_text_font(font_path=None):
    """Shrift faylini (TTFont) keshlab yuklaydi — har safar diskdan o'qimaslik uchun."""
    font_path = font_path or TEXT_FONT_PATH
    if font_path not in _TEXT_FONT_CACHE:
        from fontTools.ttLib import TTFont
        _TEXT_FONT_CACHE[font_path] = TTFont(font_path)
    return _TEXT_FONT_CACHE[font_path]


def text_to_svg(text, font_path=None, letter_spacing=40):
    """Matnni haqiqiy vektor (harf konturlari) SVG'ga aylantiradi — svg_parse_paths
    bilan to'g'ridan-to'g'ri ishlaydigan <path d="..."/> formatida.
    Rasterlash/tracing YO'Q — shrift konturlari to'g'ridan-to'g'ri Bezier
    egri chiziqlar sifatida olinadi, shuning uchun har qanday o'lchamda tiniq chiqadi.
    """
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen

    text = (text or "").strip()
    if not text:
        raise ValueError("Matn bo'sh bo'lishi mumkin emas")

    font = _load_text_font(font_path)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    units_per_em = font["head"].unitsPerEm
    space_width = units_per_em * 0.28

    x_cursor = 0.0
    d_parts = []
    any_glyph = False
    for ch in text:
        code = ord(ch)
        if ch == " ":
            x_cursor += space_width + letter_spacing
            continue
        gname = cmap.get(code) or cmap.get(ord(ch.upper())) or cmap.get(ord(ch.lower()))
        if gname is None:
            continue
        glyph = glyph_set[gname]
        svg_pen = SVGPathPen(glyph_set)
        # Y ni aylantiramiz (shrift Y-up, SVG/Lottie Y-down) va X bo'yicha kursorni siljitamiz
        transform_pen = TransformPen(svg_pen, (1, 0, 0, -1, x_cursor, 0))
        glyph.draw(transform_pen)
        d = svg_pen.getCommands()
        if d:
            d_parts.append(d)
            any_glyph = True
        x_cursor += glyph.width + letter_spacing

    if not any_glyph:
        raise ValueError("Matnda tanib bo'ladigan birorta ham harf/belgi topilmadi")

    total_width = max(x_cursor - letter_spacing, 1.0)
    full_d = " ".join(d_parts)
    height = units_per_em * 1.4
    return f'<svg viewBox="0 0 {total_width} {height}"><path d="{full_d}"/></svg>'


def _subpaths_bbox(subpaths):
    xs, ys = [], []
    for sp in subpaths:
        for (x, y) in sp["v"]:
            xs.append(x); ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def fit_subpaths_to_box(subpaths, box, padding=0.12, extra_scale=1.0):
    """box = (min_x, min_y, max_x, max_y) maqsad koordinata maydoni.
    extra_scale: 1.0 = standart o'lcham, 1.1 = 10% katta, 0.9 = 10% kichik va h.k.
    """
    bx0, by0, bx1, by1 = box
    box_w = (bx1 - bx0) * (1 - padding)
    box_h = (by1 - by0) * (1 - padding)

    sx0, sy0, sx1, sy1 = _subpaths_bbox(subpaths)
    src_w = max(sx1 - sx0, 1e-6)
    src_h = max(sy1 - sy0, 1e-6)

    scale = min(box_w / src_w, box_h / src_h) * extra_scale

    src_cx, src_cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
    dst_cx, dst_cy = (bx0 + bx1) / 2, (by0 + by1) / 2

    def tx(pt):
        x, y = pt
        return [(x - src_cx) * scale + dst_cx, (y - src_cy) * scale + dst_cy]

    def tv(vec):
        x, y = vec
        return [x * scale, y * scale]

    out = []
    for sp in subpaths:
        out.append({
            "closed": sp["closed"],
            "v": [tx(p) for p in sp["v"]],
            "i": [tv(p) for p in sp["i"]],
            "o": [tv(p) for p in sp["o"]],
        })
    return out


def hex_to_rgb01(hex_color):
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0


def subpaths_to_lottie_shape_items(subpaths, fill_hex, name="Logo"):
    r, g, b = hex_to_rgb01(fill_hex)
    items = []
    for idx, sp in enumerate(subpaths):
        items.append({
            "ty": "sh", "d": 1,
            "ks": {"a": 0, "k": {"c": sp["closed"], "i": sp["i"], "o": sp["o"], "v": sp["v"]}, "ix": idx + 2},
            "nm": f"{name} path {idx + 1}", "mn": "ADBE Vector Shape - Group", "hd": False,
        })
    items.append({
        "ty": "fl", "c": {"a": 0, "k": [r, g, b, 1], "ix": 4}, "o": {"a": 0, "k": 100, "ix": 5},
        "r": 1, "nm": "Fill", "mn": "ADBE Vector Graphic - Fill", "hd": False,
    })
    items.append({
        "ty": "tr", "p": {"a": 0, "k": [0, 0], "ix": 2}, "a": {"a": 0, "k": [0, 0], "ix": 1},
        "s": {"a": 0, "k": [100, 100], "ix": 3}, "r": {"a": 0, "k": 0, "ix": 6},
        "o": {"a": 0, "k": 100, "ix": 7}, "sk": {"a": 0, "k": 0, "ix": 4}, "sa": {"a": 0, "k": 0, "ix": 5},
        "nm": "Transform",
    })
    return items


def _svg_has_explicit_colors(subpaths):
    """SVG faylning o'zida (fill="..."/style="fill:...") kamida bitta aniq rang
    ko'rsatilganmi — shuni tekshiradi. Agar hech qanday rang ko'rsatilmagan bo'lsa
    (oddiy bir rangli ikonka), False qaytaradi va eski xulq-atvor (shablon/standart
    rang bilan bo'yash) davom etadi."""
    return any(sp.get("fill") for sp in subpaths)


def _one_color_group(subpaths, fill_hex, name="Logo", group_idx=1):
    r, g, b = hex_to_rgb01(fill_hex)
    items = subpaths_to_lottie_shape_items(subpaths, fill_hex, name=name)
    return {
        "ty": "gr", "it": items, "nm": f"{name} (generated)", "np": len(items),
        "cix": 2, "bm": 0, "ix": group_idx, "mn": "ADBE Vector Group", "hd": False,
    }


def subpaths_to_lottie_groups(subpaths, fill_hex=None, name="Logo"):
    """subpaths -> Lottie shape-group(lar) ro'yxati.

    - fill_hex berilsa (masalan foydalanuvchi aniq rang tanlagan bo'lsa) — barcha
      subpath'lar SHU rangda, BITTA guruhda chiqadi (eski, oddiy xulq-atvor).
    - fill_hex=None bo'lsa (masalan foydalanuvchi 'skip' bosgan bo'lsa) VA SVG'ning
      o'zida aniq rang(lar) ko'rsatilgan bo'lsa — har bir subpath O'ZINING SVG'dagi
      ASL rangida chiqadi (masalan logo qizil+yashil bo'lsa, ikkalasi ham saqlanadi,
      bittasiga majburan oq/bitta rang surtilmaydi).
    """
    if fill_hex is not None:
        return [_one_color_group(subpaths, fill_hex, name=name)]

    # --- ko'p rangni saqlab qolish: har bir ASL rang uchun alohida guruh ---
    order = []
    buckets = {}
    for sp in subpaths:
        color = sp.get("fill") or DEFAULT_LOGO_COLOR
        if color not in buckets:
            buckets[color] = []
            order.append(color)
        buckets[color].append(sp)

    groups = []
    for gi, color in enumerate(order):
        groups.append(_one_color_group(buckets[color], color, name=name, group_idx=gi + 1))
    return groups

TGS_TEMPLATES_DIR = os.path.join(BASE_DIR, "templates_tgs")


def list_tgs_templates():
    if not os.path.isdir(TGS_TEMPLATES_DIR):
        return []
    return sorted(f for f in os.listdir(TGS_TEMPLATES_DIR) if f.endswith(".json"))


TGS_TEMPLATES = list_tgs_templates()


def _shape_color_key(shape):
    ty = shape.get("ty")
    if ty in ("gf", "gs"):
        return _gradient_key(shape)
    k = shape.get("c", {}).get("k")
    if not isinstance(k, list) or len(k) < 3:
        return None
    if not all(isinstance(x, (int, float)) for x in k[:3]):
        return None  # animatsiyalangan rang (keyframe'lar ro'yxati) — statik emas, o'tkazib yuboramiz
    return tuple(round(float(x), 3) for x in k[:3])


def _gradient_key(shape):
    """Gradient fill/stroke ("gf"/"gs") uchun — birinchi rang-stop'ni "imzo"
    sifatida ishlatamiz, shu orqali statistikaga qo'shiladi va moslashtiriladi."""
    kobj = shape.get("g", {}).get("k")
    if not isinstance(kobj, dict):
        return None
    arr = kobj.get("k")
    if not isinstance(arr, list) or len(arr) < 4:
        return None  # animatsiyalangan gradient — o'tkazib yuboramiz
    if not all(isinstance(x, (int, float)) for x in arr[:4]):
        return None
    return ("grad", round(float(arr[1]), 2), round(float(arr[2]), 2), round(float(arr[3]), 2))


def _set_shape_color(shape, rgb):
    ty = shape.get("ty")
    if ty in ("gf", "gs"):
        _recolor_gradient(shape, rgb)
        return
    r, g, b = rgb
    k = shape.get("c", {}).get("k")
    if isinstance(k, list) and len(k) == 4:
        shape["c"]["k"] = [r, g, b, k[3]]
    else:
        shape["c"]["k"] = [r, g, b]


def _recolor_gradient(shape, rgb):
    """Gradientning yorqinlik (shine/soya) naqshini saqlab, faqat rangini
    (tint) nishon rangga moslashtiradi — masalan kulrang yaltiroq effekt
    endi tanlangan rangda yaltiraydi."""
    p = shape.get("g", {}).get("p")
    kobj = shape.get("g", {}).get("k")
    if not isinstance(kobj, dict) or not p:
        return
    arr = kobj.get("k")
    if not isinstance(arr, list):
        return
    tr, tg, tb = rgb
    n = min(int(p), len(arr) // 4)
    for i in range(n):
        base = i * 4
        orig_r, orig_g, orig_b = arr[base + 1], arr[base + 2], arr[base + 3]
        luminance = (orig_r + orig_g + orig_b) / 3.0
        arr[base + 1] = max(0.0, min(1.0, tr * luminance))
        arr[base + 2] = max(0.0, min(1.0, tg * luminance))
        arr[base + 3] = max(0.0, min(1.0, tb * luminance))


def _walk_tgs_shapes(shapes, visit_fn):
    """Rekursiv yuradi, lekin 'Svg Group 0' (logo joyi) ICHIGA KIRMAYDI —
    uni alohida _find_logo_group() orqali topib, alohida almashtiramiz."""
    for shape in shapes:
        ty = shape.get("ty")
        nm = shape.get("nm") or ""
        if ty == "gr":
            if nm == "Svg Group 0":
                continue
            visit_fn(shape)
            _walk_tgs_shapes(shape.get("it", []), visit_fn)
        else:
            visit_fn(shape)


def _polygon_area(verts):
    """Shoelace formulasi — nuqtalar ro'yxatidan ko'pburchakning HAQIQIY
    yuzasini hisoblaydi (faqat chegara qutisi emas). Bu ingichka/cho'zilgan
    shakllarni (masalan panjara tayoqchalari) noto'g'ri 'katta' deb
    hisoblashning oldini oladi — ular bbox jihatidan katta bo'lsa ham,
    haqiqiy yuzasi kichik."""
    n = len(verts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _direct_shapes_bbox_area(items):
    """Guruh ICHIDAGI (ichma-ich guruhlarsiz) shakllarning umumiy HAQIQIY
    yuzasini (har bir path uchun shoelace formulasi bilan) hisoblaydi —
    bu og'iz/tish/til/panjara kabi mayda yoki ingichka detallarni
    TANA (asosiy katta shakl)dan ajratish uchun ishlatiladi.
    Animatsiyalangan shakllar (ks.a=1, k=keyframe'lar RO'YXATI) uchun ham
    ishlaydi — birinchi keyframe'ning shaklini namuna sifatida oladi
    (aks holda animatsiyalangan TANA "0 maydon" bo'lib, butunlay
    e'tiborsiz qolib, mayda statik detallar noto'g'ri g'olib chiqardi)."""
    total = 0.0
    for it in items or []:
        if it.get("ty") == "sh":
            k = it.get("ks", {}).get("k")
            if isinstance(k, dict):
                total += _polygon_area(k.get("v", []))
            elif isinstance(k, list) and k:
                first = k[0]
                s = first.get("s") if isinstance(first, dict) else None
                if isinstance(s, list) and s and isinstance(s[0], dict):
                    total += _polygon_area(s[0].get("v", []))
    return total


def _collect_tgs_color_stats_by_area(shape_lists):
    """_collect_tgs_color_stats bilan bir xil, lekin 'necha marta uchraydi'
    o'rniga 'qancha katta joy egallaydi' (bbox maydoni) bo'yicha hisoblaydi.
    Sales News kabi ko'p mayda detalli (tish, til, ko'z) shablonlarda
    shakllar SONI bo'yicha hisoblash noto'g'ri natija berardi — masalan
    10 ta mayda oq tish-bo'lagi, 1 ta katta yashil tanadan "ko'proq"
    hisoblanib, tashqi/ichki rang noto'g'ri (tish ustiga) tushib qolardi."""
    stroke_weight = {}
    fill_weight = {}

    def visit(items):
        if not items:
            return
        area = _direct_shapes_bbox_area(items)
        for it in items:
            ty = it.get("ty")
            if ty == "gr":
                if (it.get("nm") or "") == "Svg Group 0":
                    continue
                visit(it.get("it", []))
                continue
            key = _shape_color_key(it)
            if key is None:
                continue
            if ty in ("st", "gs"):
                stroke_weight[key] = stroke_weight.get(key, 0.0) + area
            elif ty in ("fl", "gf"):
                fill_weight[key] = fill_weight.get(key, 0.0) + area

    for shapes in shape_lists:
        visit(shapes)

    dominant_stroke = max(stroke_weight, key=stroke_weight.get) if stroke_weight else None
    dominant_fill = max(fill_weight, key=fill_weight.get) if fill_weight else None
    return dominant_stroke, dominant_fill


def _collect_tgs_color_stats(shape_lists):
    stroke_counter = {}
    fill_counter = {}

    def visit(shape):
        ty = shape.get("ty")
        key = _shape_color_key(shape)
        if key is None:
            return
        if ty in ("st", "gs"):
            stroke_counter[key] = stroke_counter.get(key, 0) + 1
        elif ty in ("fl", "gf"):
            fill_counter[key] = fill_counter.get(key, 0) + 1

    for shapes in shape_lists:
        _walk_tgs_shapes(shapes, visit)

    dominant_stroke = max(stroke_counter, key=stroke_counter.get) if stroke_counter else None
    dominant_fill = max(fill_counter, key=fill_counter.get) if fill_counter else None
    return dominant_stroke, dominant_fill


def _recolor_tgs_shapes(shapes, outer_key, outer_rgb, inner_key, inner_rgb):
    def visit(shape):
        ty = shape.get("ty")
        key = _shape_color_key(shape)
        if key is None:
            return
        if ty in ("st", "gs") and outer_key is not None and key == outer_key:
            _set_shape_color(shape, outer_rgb)
        elif ty in ("fl", "gf") and inner_key is not None and key == inner_key:
            _set_shape_color(shape, inner_rgb)

    _walk_tgs_shapes(shapes, visit)


def _hsv_of(rgb):
    r, g, b = rgb[0], rgb[1], rgb[2]
    return colorsys.rgb_to_hsv(max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))


def _approx_rgb_from_key(key):
    """_shape_color_key natijasini (oddiy RGB yoki ('grad', r,g,b) gradient
    kaliti) taqqoslash uchun yagona (r,g,b) ko'rinishga keltiradi."""
    if not isinstance(key, tuple):
        return None
    if len(key) == 3:
        return key
    if len(key) == 4 and key[0] == "grad":
        return key[1:4]
    return None


def _is_similar_hue(rgb_key, ref_key, hue_tol=0.09, min_sat=0.12):
    """Ikkita rang KALITI (oddiy yoki gradient) BIR XIL 'rang oilasi'ga
    tegishlimi (masalan och yashil va to'q yashil — ham soya/yorug' joy,
    lekin bir xil ranglar oilasi) yoki yo'qligini tekshiradi. Deyarli
    kulrang/oq/qora ranglarni (past to'yinganlik) MOS DEB HISOBLAMAYMIZ —
    ular ko'pincha tish/ko'z kabi ALOHIDA elementlar bo'ladi, tananing
    soyasi emas."""
    rgb = _approx_rgb_from_key(rgb_key)
    ref_rgb = _approx_rgb_from_key(ref_key)
    if rgb is None or ref_rgb is None:
        return False
    h1, s1, v1 = _hsv_of(rgb)
    h2, s2, v2 = _hsv_of(ref_rgb)
    if s1 < min_sat or s2 < min_sat:
        return False
    dh = abs(h1 - h2)
    dh = min(dh, 1.0 - dh)
    return dh <= hue_tol


def _retint_preserve_value(color_key, target_rgb):
    """Rangni almashtiradi, lekin ASL YORQINLIKNI (V) saqlab qoladi — shu
    orqali tananing soya/yorug' joylari (highlight/shadow) buzilmaydi,
    faqat rang oilasi (hue/saturation) yangilanadi. color_key oddiy RGB
    yoki gradient kaliti ('grad', r,g,b) bo'lishi mumkin."""
    rgb = _approx_rgb_from_key(color_key) or (0.5, 0.5, 0.5)
    h, s, v = _hsv_of(rgb)
    th, ts, _tv = _hsv_of(target_rgb)
    r, g, b = colorsys.hsv_to_rgb(th, ts, v)
    return (r, g, b)


def _recolor_tgs_shapes_by_hue(shapes, outer_key, outer_rgb, inner_key, inner_rgb):
    """_recolor_tgs_shapes bilan bir xil, lekin ANIQ rang mosligini emas,
    RANG OILASI (hue) mosligini tekshiradi — shu orqali tananing turli
    soya/yorug' varianti (masalan 3 xil ottenkadagi yashil) HAMMASI
    yangi rangga o'tadi, faqat bittasi emas (avvalgi 'eski rang qolib
    ketishi' muammosining sababi shu edi)."""
    def visit(shape):
        ty = shape.get("ty")
        key = _shape_color_key(shape)
        if key is None:
            return
        if ty in ("st", "gs"):
            if outer_key is not None and (key == outer_key or _is_similar_hue(key, outer_key)):
                _set_shape_color(shape, outer_rgb if key == outer_key else _retint_preserve_value(key, outer_rgb))
        elif ty in ("fl", "gf"):
            if inner_key is not None and (key == inner_key or _is_similar_hue(key, inner_key)):
                _set_shape_color(shape, inner_rgb if key == inner_key else _retint_preserve_value(key, inner_rgb))

    _walk_tgs_shapes(shapes, visit)


def _find_logo_group(shapes):
    for shape in shapes:
        if shape.get("ty") == "gr":
            if (shape.get("nm") or "") == "Svg Group 0":
                return shape
            found = _find_logo_group(shape.get("it", []))
            if found is not None:
                return found
    return None


def _collect_shape_vertices(shapes, out):
    for s in shapes:
        if s.get("ty") == "sh":
            k = s.get("ks", {}).get("k")
            if isinstance(k, dict):
                out.extend(k.get("v", []))
        elif s.get("ty") == "gr":
            _collect_shape_vertices(s.get("it", []), out)


def _bbox_of_shape_group(shape):
    verts = []
    _collect_shape_vertices(shape.get("it", []), verts)
    if not verts:
        return (-150, -150, 150, 150)
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]
    return (min(xs), min(ys), max(xs), max(ys))


def _build_watermark_layer(canvas_w, canvas_h, ip, op, text="PREVIEW", ind=9990):
    """Diagonal, yarim-shaffof matn qatlami — pullik natijaga o'xshab
    ko'rinsayu, lekin to'g'ridan-to'g'ri saqlab, pulsiz emoji sifatida
    ishlatib bo'lmasin degan maqsadda preview'ga qo'shiladi."""
    svg = text_to_svg(text, font_path=FALLBACK_FONT, letter_spacing=30)
    subpaths, _ = svg_parse_paths(svg)
    bx0, by0, bx1, by1 = _subpaths_bbox(subpaths)
    box_w = max(bx1 - bx0, 1e-6)
    target_w = canvas_w * 1.6
    scale = target_w / box_w
    target_h = (by1 - by0) * scale
    fitted = fit_subpaths_to_box(subpaths, (0, 0, target_w, target_h), padding=0.0, extra_scale=1.0)

    items = subpaths_to_lottie_shape_items(fitted, "#9E9E9E", name="Watermark")
    for it in items:
        if it.get("ty") == "fl":
            it["o"]["k"] = 42  # yarim-shaffof

    group = {
        "ty": "gr", "it": items, "nm": "Watermark text", "np": len(items),
        "cix": 2, "bm": 0, "ix": 1, "mn": "ADBE Vector Group", "hd": False,
    }
    return {
        "ddd": 0, "ty": 4, "nm": "Watermark", "sr": 1,
        "ks": {
            "a": {"a": 0, "k": [target_w / 2, target_h / 2]},
            "p": {"a": 0, "k": [canvas_w / 2, canvas_h / 2]},
            "s": {"a": 0, "k": [100, 100]},
            "r": {"a": 0, "k": -28},
            "o": {"a": 0, "k": 100},
            "sk": {"a": 0, "k": 0},
            "sa": {"a": 0, "k": 0},
        },
        "ao": 0,
        "shapes": [group],
        "ip": ip, "op": op, "st": 0, "bm": 0, "ind": ind,
    }


def add_preview_watermark(data, text="PREVIEW"):
    """Lottie composition'ga watermark qatlamini eng ustiga qo'shadi (nusxa
    qaytaradi, kirish ma'lumotini o'zgartirmaydi)."""
    data = copy.deepcopy(data)
    w = data.get("w", 512)
    h = data.get("h", 512)
    ip = data.get("ip", 0)
    op = data.get("op", 180)
    existing_inds = [layer.get("ind", 0) for layer in data.get("layers", [])]
    ind = max(existing_inds, default=0) + 1000
    layer = _build_watermark_layer(w, h, ip, op, text=text, ind=ind)
    data.setdefault("layers", []).insert(0, layer)
    return data


def build_tgs_sticker(template_filename, svg_text, outer_hex, inner_hex, logo_hex, size_percent=100, watermark=False):
    """TGS Make shablonlari uchun: TASHQI (chegara/stroke), ICHKI FON (fill)
    va LOGO ranglarini alohida-alohida qo'llaydi, logo o'rniga esa foydalanuvchi
    SVG'sini qo'yadi. Returns (tgs_bytes, raw_json_dict)."""
    path = os.path.join(TGS_TEMPLATES_DIR, template_filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = copy.deepcopy(data)

    shape_lists = []
    for layer in data.get("layers", []):
        if layer.get("shapes"):
            shape_lists.append(layer["shapes"])
    for asset in data.get("assets", []):
        for layer in asset.get("layers", []) or []:
            if layer.get("shapes"):
                shape_lists.append(layer["shapes"])

    dominant_stroke, dominant_fill = _collect_tgs_color_stats(shape_lists)
    outer_rgb = hex_to_rgb01(outer_hex)
    inner_rgb = hex_to_rgb01(inner_hex)
    for shapes in shape_lists:
        _recolor_tgs_shapes(shapes, dominant_stroke, outer_rgb, dominant_fill, inner_rgb)

    logo_group = None
    for shapes in shape_lists:
        logo_group = _find_logo_group(shapes)
        if logo_group is not None:
            break
    if logo_group is None:
        raise ValueError(f"{template_filename} da logo joyi ('Svg Group 0') topilmadi")

    svg_subpaths, _ = svg_parse_paths(svg_text)
    box = _bbox_of_shape_group(logo_group)
    extra_scale = max(SIZE_MIN_PERCENT, min(SIZE_MAX_PERCENT, size_percent)) / 100.0
    fitted = fit_subpaths_to_box(svg_subpaths, box, extra_scale=extra_scale)
    # 'skip' bosilganda (logo_hex=None) va SVG'ning o'zida aniq rang(lar) bo'lsa —
    # o'sha ranglar (masalan qizil+yashil) saqlanadi, majburan bitta rangga bo'yalmaydi.
    if logo_hex is None and _svg_has_explicit_colors(svg_subpaths):
        logo_group["it"] = subpaths_to_lottie_groups(fitted, None, name="Logo")
    else:
        logo_group["it"] = subpaths_to_lottie_shape_items(fitted, logo_hex or DEFAULT_LOGO_COLOR, name="Logo")

    if watermark:
        data = add_preview_watermark(data)

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    return buf.getvalue(), data

