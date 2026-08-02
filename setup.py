import cx_Freeze

executables = [
    cx_Freeze.Executable(
        "main.py",
        base="Win32GUI",
        target_name="WuWa Inventory Kamera",
        icon="assets/icon.ico",
        uac_admin=True
    )
]

cx_Freeze.setup(
    name="WuWa Inventory Kamera",
    version="1.9.1",
    options={
        "build_exe": {
            "packages": ["rapidocr_onnxruntime"],
            "excludes": [
                "tkinter", "unittest", "email", "html",
                "xml", "distutils", "setuptools", "pip", "wheel"
            ],
            "include_files": [
                ("assets", "assets"),
                ("updater/echoes_extra.json", "lib/updater/echoes_extra.json"),
                ("updater/characters_extra.json", "lib/updater/characters_extra.json"),
                ("updater/character_aliases.json", "lib/updater/character_aliases.json"),
                ("updater/sonata_extra.json", "lib/updater/sonata_extra.json"),
                ("updater/roster_page_jump.json", "lib/updater/roster_page_jump.json"),
                ("updater/items_extra.json", "lib/updater/items_extra.json"),
                ("updater/weapons_extra.json", "lib/updater/weapons_extra.json"),
            ],
            "optimize": 2,
            "build_exe": "dist/v1.9.1",
            "silent_level": 0,
            "include_msvcr": True,
        }
    },
    executables=executables
)
