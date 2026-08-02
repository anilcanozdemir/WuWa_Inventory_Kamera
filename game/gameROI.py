class Coordinates:
    def __init__(self, x: int | float = 0, y: int | float = 0, w: int | float = 0, h: int | float = 0):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def __repr__(self):
        return f"Coordinates(x={self.x}, y={self.y}, w={self.w}, h={self.h})"

    def __reduce__(self):
        return (self.__class__, (self.x, self.y, self.w, self.h))

COORDINATES = {
    (16, 9): {
        (1920, 1080): {
            "terminal": Coordinates(140, 40, 150, 40),
            "shell": Coordinates(1255, 38, 165, 50),
            "offsets": {
                "page": Coordinates(16, 24)
            },
            "scroll": {
                "page": Coordinates(y=-31.25),
                "characters": Coordinates(y=-56),
                "sonata": Coordinates(y=70)
            },
            "scrapers": {
                "weapons": Coordinates(81.5, 191.5),
                "echoes": Coordinates(81.5, 326.5),
                "devItems": Coordinates(81.5, 596.5),
                "resources": Coordinates(81.5, 731.5),
            },
            "items": {
                "start": Coordinates(205, 122, 151, 181),
                "info": Coordinates(1296, 114, 558, 278),
                "description": Coordinates(1296, 114, 558, 820)
            },
            "weapons": {
                "page": Coordinates(200, 50, 130, 40),
                "start": Coordinates(205, 122, 151, 181),
                "name": Coordinates(1305, 116, 545, 55),
                "value": Coordinates(1655, 320, 190, 40),
                "level": Coordinates(1660, 235, 180, 45),
                "rank": Coordinates(1300, 530, 115, 50)
            },
            "echoes": {
                "page": Coordinates(200, 50, 130, 40),
                "start": Coordinates(205, 122, 151, 181),
                "echoCard": Coordinates(1296, 114, 558, 170),
                # Circular set badge next to the +level text — no panel scroll needed.
                "sonataIcon": Coordinates(1394, 196, 33, 33),
                # +level digits immediately right of the sonata badge.
                "echoLevel": Coordinates(1432, 193, 68, 38),
                "sonata": Coordinates(1298, 397, 554, 467),
                "mouseMovement": Coordinates(1576.5, 665.5),
                "fullStatsName": Coordinates(1380, 430, 360, 380),
                "fullStatsValue": Coordinates(1740, 430, 100, 380)
            },
            "achievements": {
                "status": Coordinates(1579, 230, 256, 65),
                "searchBar": Coordinates(388, 149),
                "searchButton": Coordinates(629, 149),
                "achievementsButton": Coordinates(1674, 790),
                "achievementsTab": Coordinates(835, 570),
            },
            "characters": {
                "offsets": {
                    "leftSide": Coordinates(y=136),
                    "rightSide": Coordinates(y=135),
                    "skillPosition": Coordinates(y=255)
                },
                "leftSide": Coordinates(82, 191),
                "rightSide": Coordinates(1810, 208),
                "rosterSlots": 6,
                # Terminal pause-menu grid → Resonators tile (scaled from 1440p calib).
                "terminalResonators": Coordinates(953, 510),
                "resonatorName": Coordinates(250, 110, 280, 50),
                "resonatorLevel": Coordinates(180, 200, 135, 80),
                "weaponName": Coordinates(257, 126, 273, 34),
                "weaponLevel": Coordinates(255, 160, 110, 35),
                "weaponRank": Coordinates(175, 355, 95, 35),
                "skillClick": Coordinates(460.5, 903),
                "skillLevel": Coordinates(390, 100, 70, 40),
                "skillButton": Coordinates(200, 980, 120, 35),
                "chainClick": Coordinates(1265, 135),
                "chainButton": Coordinates(342, 964, 110, 32),
                "skillPositions": [
                    Coordinates(755, 905),
                    Coordinates(985, 765),
                    Coordinates(1260, 705),
                    Coordinates(1535, 765),
                    Coordinates(1760, 905)
                ],
                "chainPositions": [
                    Coordinates(1395, 140),
                    Coordinates(1565, 305),
                    Coordinates(1640, 535),
                    Coordinates(1565, 765),
                    Coordinates(1400, 935),
                    Coordinates(1170, 995)
                ]
            }
        },
        # Calibrated against 2026-08-01 1440p recording (Overview name/level).
        (2560, 1440): {
            "terminal": Coordinates(187, 53, 200, 53),
            "shell": Coordinates(1673, 51, 220, 67),
            "offsets": {
                # Measured off a 1440p capture: card pitch is 235x283 with cards
                # 193x235, so the gaps are 42x48. Scaling the 1080p gaps (16, 24)
                # by 4/3 gave (21, 32), which put clicks only 70px below a card's
                # top edge instead of centring them.
                "page": Coordinates(42, 48)
            },
            "scroll": {
                # Wheel notches are resolution-independent: the game advances by
                # row units, not raw pixels. Scaling the 1080p value (-31.25) by
                # 4/3 to -42, then to a pixel-derived -64.46, made each "page"
                # jump ~8 rows and skip half the inventory.
                "page": Coordinates(y=-31.25),
                # Wheel notches to advance one roster "page" after scanning 6 slots.
                # Pixel-drag of 6*180 overshot (Raven → Danjin). -5 ≈ next window.
                "characters": Coordinates(y=-5),
                "sonata": Coordinates(y=93)
            },
            "scrapers": {
                "weapons": Coordinates(109, 255),
                "echoes": Coordinates(109, 435),
                "devItems": Coordinates(109, 795),
                "resources": Coordinates(109, 975),
            },
            "items": {
                "start": Coordinates(236, 185, 193, 235),
                "info": Coordinates(1728, 152, 744, 371),
                "description": Coordinates(1728, 152, 744, 1093)
            },
            "weapons": {
                "page": Coordinates(267, 67, 173, 53),
                "start": Coordinates(236, 185, 193, 235),
                "name": Coordinates(1740, 155, 727, 73),
                "value": Coordinates(2207, 427, 253, 53),
                # Live-probed 1440p: "Level 80/80" band is ~y=310 (not the old
                # 2213,313 AT that sat on empty space to the right).
                "level": Coordinates(1740, 305, 360, 50),
                "rank": Coordinates(1733, 707, 153, 67)
            },
            "echoes": {
                "page": Coordinates(267, 67, 173, 53),
                "start": Coordinates(236, 185, 193, 235),
                "echoCard": Coordinates(1728, 152, 744, 227),
                # Circular set badge next to +level (measured off a 1440p capture).
                "sonataIcon": Coordinates(1859, 261, 44, 44),
                # +level digits immediately right of the sonata badge.
                "echoLevel": Coordinates(1910, 258, 90, 50),
                "sonata": Coordinates(1731, 529, 739, 623),
                "mouseMovement": Coordinates(2102, 887),
                "fullStatsName": Coordinates(1840, 573, 480, 507),
                "fullStatsValue": Coordinates(2320, 573, 133, 507)
            },
            "achievements": {
                "status": Coordinates(2105, 307, 341, 87),
                "searchBar": Coordinates(517, 199),
                "searchButton": Coordinates(839, 199),
                "achievementsButton": Coordinates(2232, 1053),
                "achievementsTab": Coordinates(1113, 760),
            },
            "characters": {
                "offsets": {
                    # Measured off open_chars overview: tab centers ~180px apart.
                    "leftSide": Coordinates(y=180),
                    # Live-recorded 2026-08-02 roster (tools/record_roster_clicks.py).
                    "rightSide": Coordinates(y=174),
                    # Fallback uniform step (legacy). Prefer skillNodeOffsets below.
                    "skillPosition": Coordinates(y=350)
                },
                # Overview tab (active ring). Also discoverable via header OCR.
                "leftSide": Coordinates(108, 254),
                "tabOverview": Coordinates(108, 254),
                "tabWeapon": Coordinates(108, 434),
                "tabEcho": Coordinates(108, 624),
                "tabForte": Coordinates(108, 814),
                "tabChain": Coordinates(108, 975),
                # Candidate Y list used when discovering tabs by header OCR.
                "tabStripYs": [254, 434, 624, 814, 975],
                # Live-recorded 2026-08-02 timed page jump (~4.16s) → data/roster_page_jump.json
                "rightSide": Coordinates(2410, 301),
                "rosterSlots": 6,
                "rosterSlotYs": [301, 461, 648, 828, 990, 1167],
                "pageJumpDrag": -1072,
                "pageJumpDurationS": 4.159,
                "pageJumpStart": Coordinates(2417, 1180),
                "pageJumpEnd": Coordinates(2414, 108),
                # Live-calibrated 2026-08-02: OCR "Resonators" label ~(1271,792);
                # icon center sits above the label in the middle-left grid cell.
                "terminalResonators": Coordinates(1270, 680),
                "resonatorName": Coordinates(260, 248, 520, 56),
                # Tight box around "Lv.80/80" — wide crop only OCR'd "/80" / "Lv.8.80".
                "resonatorLevel": Coordinates(300, 345, 180, 45),
                # Live-recorded 2026-08-02 Weapon tab (tools/record_weapon_rois.py).
                # Level box widened to inventory-style width so "Level 80/80" isn't clipped.
                "weaponName": Coordinates(270, 264, 464, 51),
                "weaponLevel": Coordinates(271, 335, 360, 50),
                "weaponRank": Coordinates(276, 565, 104, 43),
                # Unused on modern Forte (tree already visible). Kept for 1080p parity.
                "skillClick": Coordinates(614, 1204),
                # Left detail panel "Lv. 8" — OCR needs 2× upscale of this crop.
                "skillLevel": Coordinates(640, 110, 180, 70),
                # "Activated" label on node detail (left panel bottom). Also searched wider in code.
                "skillButton": Coordinates(200, 1220, 400, 100),
                # Upstream chainClick (1265,135) × 4/3 — first click on the RC graphic, not the tab.
                "chainClick": Coordinates(1270, 1271),
                "chainButton": Coordinates(369, 1108, 160, 48),
                # Live-recorded 2026-08-02 (tools/record_forte_clicks.py).
                "skillPositions": [
                    Coordinates(622, 1178),  # Normal Attack
                    Coordinates(915, 1007),  # Resonance
                    Coordinates(1289, 918),  # Forte
                    Coordinates(1635, 996),  # Liberation
                    Coordinates(1934, 1148), # Intro
                ],
                # Y deltas above each skill (recorded node clicks).
                "skillNodeOffsets": [
                    [336, 644],
                    [349, 649],
                    [300, 604],
                    [343, 611],
                    [318, 607],
                ],
                # Absolute node clicks (same recording) — preferred when present.
                "skillNodes": [
                    [Coordinates(620, 842), Coordinates(637, 534)],
                    [Coordinates(909, 658), Coordinates(920, 358)],
                    [Coordinates(1292, 618), Coordinates(1295, 314)],
                    [Coordinates(1619, 653), Coordinates(1622, 385)],
                    [Coordinates(1923, 830), Coordinates(1953, 541)],
                ],
                "chainPositions": [
                    Coordinates(1270, 1271),
                    Coordinates(1500, 1203),
                    Coordinates(1712, 1091),
                    Coordinates(1922, 854),
                    Coordinates(2021, 682),
                    Coordinates(2074, 365)
                ],
                # Character Echo equip UI — live-recorded 2026-08-02 (record_echo_rois.py).
                # Enter from overview arc → left-rail slots; right panel = name/level/sonata/stats.
                "echoEnterClick": Coordinates(1957, 333),
                "echoSlotPositions": [
                    Coordinates(175, 325),
                    Coordinates(178, 529),
                    Coordinates(147, 701),
                    Coordinates(157, 812),
                    Coordinates(142, 970),
                ],
                "echoDetailName": Coordinates(2002, 202, 358, 31),
                "echoDetailLevel": Coordinates(2355, 190, 90, 45),
                # Live-recorded 2026-08-02 (tools/record_echo_stats_rois.py).
                "echoFullStatsName": Coordinates(2053, 308, 326, 319),
                "echoFullStatsValue": Coordinates(2367, 312, 92, 314),
                # Echo overview left panel — "Sonata Effect" / set name (N/5).
                "echoOverviewSonata": Coordinates(200, 980, 560, 200),
                # Equip UI right-panel strip (skill / equipped set line).
                "echoSonataText": Coordinates(1980, 750, 520, 450),
            }
        }
    },
    (16, 10): {
        (1680, 1050): {
            "terminal": Coordinates(125, 32, 150, 40),
            "shell": Coordinates(1100, 35, 145, 40),
            "offsets": {
                "page": Coordinates(16, 24),
                "characters": Coordinates(y=-56),
                "sonata": Coordinates(y=70),
            },
            "scroll": {
                "page": Coordinates(y=-31.70),
                "characters": Coordinates(y=-56),
                "sonata": Coordinates(y=70)
            },
            "scrapers": {
                "weapons": Coordinates(71.5, 167),
                "echoes": Coordinates(71.5, 285),
                "devItems": Coordinates(71.5, 521),
                "resources": Coordinates(71.5, 639),
            },
            "items": {
                "start": Coordinates(180, 104, 130, 162),
                "info": Coordinates(1136, 154, 485, 240),
                "description": Coordinates(1136, 154, 485, 715)
            },
            "weapons": {
                "page": Coordinates(175, 40, 130, 40),
                "start": Coordinates(180, 104, 130, 162),
                "name": Coordinates(1140, 152, 480, 50),
                "value": Coordinates(1430, 330, 190, 40),
                "level": Coordinates(1435, 255, 180, 45),
                "rank": Coordinates(1135, 510, 100, 50)
            },
            "echoes": {
                "page": Coordinates(175, 40, 130, 40),
                "start": Coordinates(180, 104, 130, 162),
                "echoCard": Coordinates(1136, 152, 486, 152),
                "sonataIcon": Coordinates(1220, 171, 29, 29),
                "echoLevel": Coordinates(1254, 168, 60, 34),
                "sonata": Coordinates(1135, 400, 486, 408),
                "mouseMovement": Coordinates(1576.5, 665.5),
                "fullStatsName": Coordinates(1200, 420, 320, 380),
                "fullStatsValue": Coordinates(1510, 420, 100, 380)
            },
            "achievements": {
                "status": Coordinates(1579, 197, 256, 65),
                "searchBar": Coordinates(388, 129),
                "searchButton": Coordinates(550, 129),
                "achievementsButton": Coordinates(1465, 690),
                "achievementsTab": Coordinates(735, 570),
            },
            "characters": {
                "offsets": {
                    "leftSide": Coordinates(y=119),
                    "rightSide": Coordinates(y=93.5),
                    "skillPosition": Coordinates(y=220)
                },
                "leftSide": Coordinates(68, 167.5),
                "rightSide": Coordinates(1586.5, 177.5),
                "resonatorName": Coordinates(220, 102, 280, 50),
                "resonatorLevel": Coordinates(160, 180, 135, 80),
                "weaponName": Coordinates(225, 118, 240, 34),
                "weaponLevel": Coordinates(215, 150, 110, 35),
                "weaponRank": Coordinates(143, 320, 93, 35),
                "skillClick": Coordinates(403, 845),
                "skillLevel": Coordinates(340, 95, 70, 40),
                "skillButton": Coordinates(170, 950, 120, 35),
                "chainClick": Coordinates(1109, 174),
                "chainButton": Coordinates(292, 936, 110, 32),
                "skillPositions": [
                    Coordinates(660, 842),
                    Coordinates(864, 722),
                    Coordinates(1103, 667),
                    Coordinates(1342, 722),
                    Coordinates(1545, 842)
                ],
                "chainPositions": [
                    Coordinates(1224, 176),
                    Coordinates(1369, 319),
                    Coordinates(1424, 519),
                    Coordinates(1369, 724),
                    Coordinates(1224, 864),
                    Coordinates(1024, 919)
                ]
            }
        }
    }
}