"""fontTools glyph -> Lottie vector shape conversion."""
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen


class LottiePen(BasePen):
    """Collects glyph outline as Lottie-style bezier contours (v/i/o)."""

    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.contours = []
        self._cur = None

    def _moveTo(self, pt):
        self._cur = {"v": [[pt[0], pt[1]]], "i": [[0, 0]], "o": [[0, 0]]}

    def _lineTo(self, pt):
        self._cur["v"].append([pt[0], pt[1]])
        self._cur["i"].append([0, 0])
        self._cur["o"].append([0, 0])

    def _curveToOne(self, p1, p2, p3):
        lv = self._cur["v"][-1]
        self._cur["o"][-1] = [p1[0] - lv[0], p1[1] - lv[1]]
        self._cur["v"].append([p3[0], p3[1]])
        self._cur["i"].append([p2[0] - p3[0], p2[1] - p3[1]])
        self._cur["o"].append([0, 0])

    def _closePath(self):
        v = self._cur["v"]
        if len(v) > 1 and v[0] == v[-1]:
            self._cur["i"][0] = self._cur["i"][-1]
            v.pop()
            self._cur["i"].pop()
            self._cur["o"].pop()
        self.contours.append(self._cur)
        self._cur = None

    def _endPath(self):
        if self._cur is not None:
            self._closePath()


CANON_UPM = 1000


def _units_per_em(font):
    try:
        return font["head"].unitsPerEm or CANON_UPM
    except Exception:
        return CANON_UPM


def glyph_contours(font, char, norm=1.0):
    cmap = font.getBestCmap()
    cp = ord(char)
    if cp not in cmap:
        return None, 0
    gname = cmap[cp]
    glyphSet = font.getGlyphSet()
    pen = LottiePen(glyphSet)
    glyphSet[gname].draw(pen)
    advance = glyphSet[gname].width * norm
    if norm != 1.0:
        for c in pen.contours:
            c["v"] = [[x * norm, y * norm] for x, y in c["v"]]
            c["i"] = [[dx * norm, dy * norm] for dx, dy in c["i"]]
            c["o"] = [[dx * norm, dy * norm] for dx, dy in c["o"]]
    return pen.contours, advance


def get_cap_height(font):
    try:
        ch = font["OS/2"].sCapHeight
        if ch:
            return ch
    except Exception:
        pass
    return int(font["hhea"].ascent * 0.72)


def layout_word(word, font_path, fallback_font_path=None):
    """Returns (font, chars_data, total_width_canon_units, cap_height_canon_units).

    Glyphs missing from the primary font (e.g. Cyrillic in a Latin-only
    display font) are looked up in fallback_font_path if given. Coordinates
    from both fonts are normalized to a shared canonical unitsPerEm first,
    so a fallback glyph's size/advance line up with the primary font's even
    though the two fonts may use different internal unit scales."""
    font = TTFont(font_path)
    primary_cmap = font.getBestCmap()
    primary_norm = CANON_UPM / _units_per_em(font)
    cap_height = get_cap_height(font) * primary_norm

    fallback_font = None
    fallback_norm = 1.0
    fallback_cmap = {}
    if fallback_font_path:
        fallback_font = TTFont(fallback_font_path)
        fallback_cmap = fallback_font.getBestCmap()
        fallback_norm = CANON_UPM / _units_per_em(fallback_font)

    pen_x = 0
    chars_data = []
    for ch in word:
        cp = ord(ch)
        if cp in primary_cmap:
            contours, advance = glyph_contours(font, ch, primary_norm)
        elif cp in fallback_cmap:
            contours, advance = glyph_contours(fallback_font, ch, fallback_norm)
        else:
            contours, advance = None, 0
        if advance == 0 and contours is None:
            # unknown glyph: skip drawing but keep some advance (space width guess)
            advance = font["hmtx"]["space"][0] * primary_norm if "space" in font["hmtx"].mtx else cap_height
        chars_data.append((ch, contours, advance, pen_x))
        pen_x += advance
    return font, chars_data, pen_x, cap_height


def build_lottie_letter_groups(word, font_path, target_height, center_y,
                                stroke_rgba, stroke_width, fill_rgba, max_width=None,
                                center_x=0.0, fallback_font_path=None):
    """Build Lottie 'gr' shape groups (one per letter) for the given word,
    scaled so caps-height == target_height, horizontally centered at
    x=center_x and vertically centered at y=center_y (Lottie/AE coordinate
    convention: y grows down).

    center_x/center_y should be the center (in the layer's own local
    coordinate space) where the original placeholder text was drawn. Some
    templates position their text layer via the layer transform (anchor +
    position both at the visual center, local content centered at the
    origin), while others bake the badge's absolute position directly into
    the shape coordinates (anchor/position left at 0,0). Centering new text
    on the original content's own center keeps it aligned the same way the
    original placeholder was, regardless of which convention a given
    template uses - and, being center-based rather than baseline-based, it
    stays vertically centered automatically even when max_width shrinks the
    word down, with no separate correction needed.

    If max_width is given and the word would render wider than that at the
    normal (height-based) scale, the whole word is shrunk down (never
    enlarged) just enough to fit within max_width, so long words don't
    overflow the template's banner/badge."""
    font, chars_data, total_w_units, cap_height = layout_word(word, font_path, fallback_font_path)
    scale = target_height / cap_height
    if max_width:
        width_at_scale = total_w_units * scale
        if width_at_scale > max_width:
            scale = max_width / total_w_units
    total_width = total_w_units * scale
    x_start = center_x - total_width / 2
    final_height = scale * cap_height
    baseline_y = center_y + final_height / 2

    groups = []
    for ch, contours, advance, pen_x0 in chars_data:
        if not contours:
            continue
        sh_items = []
        for c in contours:
            v = [[x * scale + pen_x0 * scale + x_start, -y * scale + baseline_y] for x, y in c["v"]]
            i = [[dx * scale, -dy * scale] for dx, dy in c["i"]]
            o = [[dx * scale, -dy * scale] for dx, dy in c["o"]]
            sh_items.append({
                "ty": "sh", "ix": 1,
                "ks": {"a": 0, "k": {"i": i, "o": o, "v": v, "c": True}},
                "nm": ch, "mn": "ADBE Vector Shape - Group", "hd": False
            })
        grp_items = list(sh_items)
        if len(sh_items) > 1:
            grp_items.append({
                "ty": "mm", "mm": 1, "nm": "Merge Paths",
                "mn": "ADBE Vector Filter - Merge", "hd": False
            })
        grp_items.append({
            "ty": "st", "c": {"a": 0, "k": stroke_rgba}, "o": {"a": 0, "k": 100},
            "w": {"a": 0, "k": stroke_width}, "lc": 1, "lj": 1, "ml": 4,
            "nm": "Stroke", "mn": "ADBE Vector Graphic - Stroke", "hd": False
        })
        grp_items.append({
            "ty": "fl", "c": {"a": 0, "k": fill_rgba}, "o": {"a": 0, "k": 100},
            "r": 1, "nm": "Fill", "mn": "ADBE Vector Graphic - Fill", "hd": False
        })
        grp_items.append({
            "ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
            "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100},
            "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}, "nm": "Transform"
        })
        groups.append({
            "ty": "gr", "it": grp_items, "nm": ch, "np": len(grp_items),
            "cix": 2, "bm": 0, "ix": 1, "mn": "ADBE Vector Group", "hd": False
        })
    return groups
