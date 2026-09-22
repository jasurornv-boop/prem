import os

BASE = os.path.dirname(__file__)
FONT = os.path.join(BASE, "fonts", "Poppins-Bold.ttf")
# used for characters Poppins doesn't have glyphs for (Cyrillic, i.e. Russian/Uzbek-kirill)
FALLBACK_FONT = os.path.join(BASE, "fonts", "DejaVuSans-Bold.ttf")

TEMPLATES = {
    "payshanba": {
        "label": "PAYSHANBA",
        "file": os.path.join(BASE, "templates", "payshanba.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 14,
                "fill": [0.102, 0.6118, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 104, "baseline_y": 6, "max_width": 440,
            },
            {
                "path": ("assets", "comp_1"), "ind": 15,
                "fill": [0.1176, 0.2196, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 104, "baseline_y": 6, "max_width": 440,
            },
        ],
    },
    "millioner": {
        "label": "Millioner",
        "file": os.path.join(BASE, "templates", "millioner.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 14,
                "fill": [0.278, 0.278, 0.278, 1],
                "stroke": [1, 1, 1, 1], "stroke_w": 0.01,
                "target_height": 60.845, "baseline_y": 0.664, "max_width": 440,
            },
        ],
    },
    "jasur": {
        "label": "Jasur",
        "file": os.path.join(BASE, "templates", "jasur.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 1,
                "fill": [0.4, 0.0, 1.0, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 141.12, "baseline_y": 1.96, "max_width": 440,
            },
            {
                "path": ("assets", "comp_1"), "ind": 2,
                "fill": [0.1569, 0.0039, 0.3686, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 141.12, "baseline_y": 1.96, "max_width": 440,
            },
        ],
    },
    "axi": {
        "label": "AXI",
        "file": os.path.join(BASE, "templates", "axi.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 3,
                "fill": [0.102, 0.6118, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 104, "baseline_y": 6, "max_width": 440,
            },
            {
                "path": ("assets", "comp_1"), "ind": 4,
                "fill": [0.1176, 0.2196, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 104, "baseline_y": 6, "max_width": 440,
            },
        ],
    },
    "spam": {
        "label": "SPAM",
        "file": os.path.join(BASE, "templates", "spam.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 1,
                "fill": [0.8902, 0.1216, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 98.787, "baseline_y": 1.104, "max_width": 440, "y_nudge": 2,
            },
            {
                "path": ("assets", "comp_1"), "ind": 2,
                "fill": [0.3255, 0.1647, 0.1686, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 98.787, "baseline_y": 1.104, "max_width": 440, "y_nudge": 2,
            },
        ],
    },
    "sooqa": {
        "label": "SOOQA",
        "file": os.path.join(BASE, "templates", "sooqa.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 3,
                "fill": [0.102, 0.6118, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 104, "baseline_y": 6, "max_width": 266,
            },
            {
                "path": ("assets", "comp_1"), "ind": 4,
                "fill": [0.1176, 0.2196, 0.1216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 104, "baseline_y": 6, "max_width": 266,
            },
        ],
    },
    "munis": {
        "label": "MUNIS",
        "file": os.path.join(BASE, "templates", "munis.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 1,
                "fill": [1, 0, 0, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 144, "baseline_y": 2, "max_width": 373,
            },
        ],
    },
    "vip": {
        "label": "VIP",
        "file": os.path.join(BASE, "templates", "vip.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 1,
                "fill": [0.9255, 0.6745, 0.3373, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 127, "baseline_y": 0, "max_width": 224,
            },
            {
                "path": ("assets", "comp_1"), "ind": 2,
                "fill": [0.451, 0.3098, 0.1255, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 127, "baseline_y": 0, "max_width": 224,
            },
        ],
    },
    "fake": {
        "label": "FAKE",
        "file": os.path.join(BASE, "templates", "fake.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 3279,
                "fill": [0.33, 0.67, 0.92, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 72, "baseline_y": 124, "max_width": 166,
            },
        ],
    },
    "scam": {
        "label": "SCAM",
        "file": os.path.join(BASE, "templates", "scam.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 647,
                "fill": [0.9, 0.35, 0.28, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 72, "baseline_y": 125, "max_width": 166,
            },
        ],
    },
    "busy": {
        "label": "BUSY",
        "file": os.path.join(BASE, "templates", "busy.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 2031,
                "fill": [1, 0.72, 0, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 72, "baseline_y": 125, "max_width": 166,
            },
        ],
    },
    "admin": {
        "label": "ADMIN",
        "file": os.path.join(BASE, "templates", "admin.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 0,
                "fill": [0.039, 0.529, 0.847, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 55, "baseline_y": 95, "max_width": 129,
            },
        ],
    },
    "hold": {
        "label": "HOLD",
        "file": os.path.join(BASE, "templates", "hold.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_0"), "ind": 1,
                "fill": [0.9686, 0.6549, 0.149, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 83, "baseline_y": 30, "max_width": 342,
            },
            {
                "path": ("assets", "comp_0"), "ind": 3,
                "fill": [0.9686, 0.6549, 0.149, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 83, "baseline_y": 30, "max_width": 342,
            },
        ],
    },
    "zzz": {
        "label": "ZZZ",
        "file": os.path.join(BASE, "templates", "zzz.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 0,
                "fill": [0.039, 0.529, 0.847, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 55, "baseline_y": 95, "max_width": 129,
            },
        ],
    },
    "police": {
        "label": "POLICE",
        "file": os.path.join(BASE, "templates", "police.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 1,
                "fill": [0.7216, 0, 0, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 22, "baseline_y": 0, "max_width": 108,
            },
        ],
    },
    "tired": {
        "label": "TIRED",
        "file": os.path.join(BASE, "templates", "tired.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 1,
                "fill": [1, 0.6392, 0.102, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 21, "baseline_y": 0, "max_width": 86,
            },
            {
                "path": ("layers",), "ind": 3,
                "fill": [1, 0.6392, 0.102, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 21, "baseline_y": 0, "max_width": 86,
            },
        ],
    },
    "milf": {
        "label": "MILF",
        "file": os.path.join(BASE, "templates", "milf.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 1,
                "fill": [0.2588, 0.6196, 0.898, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 21, "baseline_y": 0, "max_width": 67,
            },
        ],
    },
    "work": {
        "label": "WORK",
        "file": os.path.join(BASE, "templates", "work.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_0"), "ind": 1,
                "fill": [0.6118, 0.8627, 0.3137, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 83, "baseline_y": 11, "max_width": 376,
            },
            {
                "path": ("assets", "comp_0"), "ind": 3,
                "fill": [0.6118, 0.8627, 0.3137, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 83, "baseline_y": 11, "max_width": 376,
            },
        ],
    },
    "asliddin": {
        "label": "ASLIDDIN",
        "file": os.path.join(BASE, "templates", "asliddin.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_0"), "ind": 1,
                "fill": [0.2667, 0.2667, 0.2667, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 141, "baseline_y": 2, "max_width": 440,
            },
            {
                "path": ("assets", "comp_0"), "ind": 2,
                "fill": [1, 1, 1, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 141, "baseline_y": 2, "max_width": 440,
            },
        ],
    },
    "bekzod": {
        "label": "Bekzod",
        "file": os.path.join(BASE, "templates", "bekzod.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 1,
                "fill": [0, 0, 1, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 110, "baseline_y": 0, "max_width": 400,
            },
        ],
    },
    "bahor": {
        "label": "Bahor",
        "file": os.path.join(BASE, "templates", "bahor.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_1"), "ind": 1,
                "fill": [0.7765, 0, 0.8039, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 134, "baseline_y": 0, "max_width": 345,
            },
        ],
    },
    "great": {
        "label": "Great",
        "file": os.path.join(BASE, "templates", "great.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_0"), "ind": 1,
                "fill": [0.847, 0.7216, 0.3216, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 98, "baseline_y": 0, "max_width": 460,
            },
            {
                "path": ("assets", "comp_0"), "ind": 2,
                "fill": [0, 0, 0, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 98, "baseline_y": 0, "max_width": 460,
            },
        ],
    },
    "hack": {
        "label": "HACK",
        "file": os.path.join(BASE, "templates", "hack.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 1,
                "fill": [0.0, 0.8706, 0.0039, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 123.662, "baseline_y": 0, "max_width": 400,
            },
            {
                "path": ("layers",), "ind": 2,
                "fill": [0.0, 0.6157, 0.0, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 123.662, "baseline_y": 0, "max_width": 400,
            },
        ],
    },
    "usdt": {
        "label": "USDT",
        "file": os.path.join(BASE, "templates", "usdt.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("layers",), "ind": 3,
                "fill": [1, 1, 1, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 129.85, "baseline_y": 0, "max_width": 410,
            },
            {
                "path": ("layers",), "ind": 5,
                "fill": [0.0, 0.5765, 0.5765, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 129.85, "baseline_y": 0, "max_width": 410,
            },
        ],
    },
    "vip_stars": {
        "label": "VIP",
        "file": os.path.join(BASE, "templates", "vip_stars.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_0"), "ind": 6,
                "fill": [1.0, 0.0, 0.2824, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 154, "baseline_y": 0, "max_width": 300,
            },
            {
                # Second, independent "VIP" that lives directly in the main
                # composition (ind=18, parented to Null 1) rather than
                # inside the comp_0 precomp - a gold-stroke, no-fill
                # duplicate of the same word that was previously missed,
                # so it kept showing the old placeholder text on every
                # render regardless of what name was requested.
                "path": ("layers",), "ind": 18,
                "fill": [0, 0, 0, 0],
                "stroke": [1.0, 0.949250284831, 0.137254887001, 1], "stroke_w": 2,
                "target_height": 154, "baseline_y": 0, "max_width": 300,
            },
        ],
    },
    "muzlik": {
        "label": "Muzlik",
        "file": os.path.join(BASE, "templates", "muzlik.json"),
        "font": FONT,
        "text_layers": [
            {
                "path": ("assets", "comp_2"), "ind": 2,
                "fill": [0.011764705882, 0.223529411765, 0.356862745098, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 148, "baseline_y": 0, "max_width": 400,
            },
            {
                "path": ("assets", "comp_2"), "ind": 1,
                "fill": [0.639215707779, 0.960784316063, 1, 1],
                "stroke": None, "stroke_w": 0,
                "target_height": 148, "baseline_y": 0, "max_width": 400,
            },
        ],
    },
}

# order + custom emoji ids for the /start buttons
TEMPLATE_ORDER = [
    "jasur", "axi", "spam", "munis", "asliddin", "millioner", "payshanba", "work",
    "bekzod", "bahor", "great", "muzlik", "hack", "usdt", "vip_stars", "cs2",
]
EMOJI_IDS = {
    "jasur": "5431461710340859300",
    "axi": "5431481213787349538",
    "sooqa": "5433934550646430895",
    "spam": "5431613610449217914",
    "munis": "5433883912982010907",
    "vip": "5431661842931946717",
    "fake": "5431573074547875595",
    "scam": "5431606472213567445",
    "busy": "5431815851869248035",
    "admin": "5431719150680581432",
    "hold": "5431548734968212443",
    "zzz": "5431631619247084823",
    "police": "5431895149850441601",
    "tired": "5431351793537823696",
    "milf": "5431377245514015222",
    "work": "5431797422164585163",
    "asliddin": "5431813459572466622",
    "millioner": "5222056551145022461",
    "bekzod": "5460954709596584859",
    "bahor": "5460919529519464795",
    "great": "5438603815752344896",
    "muzlik": "5359602410648001492",
    "hack": "5467549614699746690",
    "usdt": "5467715731149855116",
    "vip_stars": "5467441059401342772",
}
# "off" (custom emoji 5433932278608729966) va nomsiz 15-shablon (custom emoji
# 5431463037485750808) hali qo'shilmagan: off.json bo'sh fayl edi (qayta
# yuboring), 15-shablonga esa hali nom berilmagan.

# 16-chi Name Emoji: CS 2. Both original text layers keep their transforms.
CS2_EMOJI_SET = "Abuemojibro5837300296340e81_by_emojichi_bot"
CS2_EMOJI_URL = "https://t.me/addemoji/" + CS2_EMOJI_SET
CS2_FILE_UNIQUE_ID = "AgADWZkAAkuBCUk"
TEMPLATES["cs2"] = {
    "label": "CS 2",
    "file": os.path.join(BASE, "templates", "cs2.json"),
    "font": FONT,
    "text_layers": [
        {
            "path": ("assets", "comp_2"), "ind": 1,
            "fill": [0.992156922583, 0.537254901961, 0.003921568627, 1],
            "stroke": None, "stroke_w": 0,
            "target_height": 58.35, "max_width": 157.05,
        },
        {
            "path": ("assets", "comp_2"), "ind": 2,
            "fill": [1, 1, 1, 1],
            "stroke": None, "stroke_w": 0,
            "target_height": 58.35, "max_width": 157.05,
        },
    ],
}
