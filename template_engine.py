import copy
import gzip
import json

from font_render import build_lottie_letter_groups
from templates_config import FALLBACK_FONT


def _get_layer_list(data, path):
    if path[0] == "layers":
        return data["layers"]
    if path[0] == "assets":
        asset_id = path[1]
        asset = next(a for a in data["assets"] if a["id"] == asset_id)
        return asset["layers"]
    raise ValueError(f"unknown path {path}")


def _original_center(shapes):
    """Find the center (x, y) of the placeholder text currently baked into
    a layer's shapes, in that layer's own local coordinate space.

    Templates position their text two different ways: some center the
    content at local (0, 0) and rely on the layer's anchor+position
    transform to place it on the canvas; others leave anchor/position at
    (0, 0) and bake the absolute canvas position directly into the shape
    coordinates. Always assuming the old placeholder was centered at the
    origin only holds for the first group - for the second it silently
    shifts new text off to one side (or, vertically, leaves it sitting
    noticeably high/low in its badge once a manually-guessed baseline
    number doesn't quite match). Measuring the actual bounding box of
    what's already there works for both cases, for both axes."""
    xs, ys = [], []

    def walk(items):
        for it in items:
            if it.get("ty") == "gr":
                walk(it.get("it", []))
            elif it.get("ty") == "sh":
                for v in it["ks"]["k"].get("v", []):
                    xs.append(v[0])
                    ys.append(v[1])

    walk(shapes)
    if not xs:
        return 0.0, 0.0
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def _own_scale(layer):
    s = layer.get("ks", {}).get("s")
    if not s or not isinstance(s.get("k"), list) or not s["k"] or isinstance(s["k"][0], dict):
        return 1.0, 1.0
    sx, sy = s["k"][0], s["k"][1]
    return (sx / 100.0 or 1.0), (sy / 100.0 or 1.0)


def _layer_scale(layer, layer_list=None):
    """The layer's effective scale (sx, sy) as fractions (100% -> 1.0),
    including any scale inherited from a parent layer (AE-style layer
    parenting multiplies transforms down the chain - a layer that leaves
    its own scale at 100% but is parented to one scaled at 129% still
    ends up rendering at 129%, and treating it as 100% would make it come
    out the wrong size relative to its sibling).

    Several templates have their text layer scaled well past 100% inside
    the template itself (as high as ~380%). target_height/max_width in the
    config are meant to describe the final size the word should appear at
    on the sticker - if we don't account for this per-layer (and inherited)
    scale first, that amplification stacks on top and the word renders far
    larger (and can spill past the intended badge) than the configured
    numbers say."""
    sx, sy = _own_scale(layer)
    parent_ind = layer.get("parent")
    if parent_ind is not None and layer_list is not None:
        parent = next((l for l in layer_list if l.get("ind") == parent_ind), None)
        if parent is not None:
            psx, psy = _layer_scale(parent, layer_list)
            sx, sy = sx * psx, sy * psy
    return sx, sy


def render_template(template_cfg: dict, word: str) -> dict:
    with open(template_cfg["file"], encoding="utf-8") as f:
        data = json.load(f)
    data = copy.deepcopy(data)
    font_path = template_cfg["font"]

    for tl in template_cfg["text_layers"]:
        layer_list = _get_layer_list(data, tl["path"])
        layer = next(l for l in layer_list if l.get("ind") == tl["ind"])

        center_x, center_y = _original_center(layer.get("shapes", []))
        scale_x, scale_y = _layer_scale(layer, layer_list)
        y_nudge = tl.get("y_nudge", 0)
        center_y = center_y - (y_nudge / scale_y if scale_y else y_nudge)
        stroke_rgba = tl["stroke"] or [0, 0, 0, 0]
        stroke_w = tl["stroke_w"]
        max_width = tl.get("max_width")
        groups = build_lottie_letter_groups(
            word, font_path,
            tl["target_height"] / scale_y, center_y,
            stroke_rgba, stroke_w, tl["fill"],
            max_width=(max_width / scale_x) if max_width else None,
            center_x=center_x,
            fallback_font_path=FALLBACK_FONT,
        )
        layer["shapes"] = groups
        # NOTE: anchor/position are deliberately left untouched. New text is
        # centered at the same local x the old placeholder occupied, so
        # whatever anchor/position math the template already had continues
        # to land it in the right spot on the canvas.

    return data


def save_as_tgs(lottie_dict: dict, out_path: str):
    raw = json.dumps(lottie_dict, separators=(",", ":")).encode("utf-8")
    with gzip.open(out_path, "wb") as f:
        f.write(raw)
