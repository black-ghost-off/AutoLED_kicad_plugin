import os

import pcbnew


class AutoLedPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "AutoLED: place LEDs on image shape"
        self.category = "Placement"
        self.description = ("Place WS2812 / SMD LEDs as a 2D grid inside a shape from an "
                            "SVG, PNG or BMP image; export JSON/TXT/C header and a schematic")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        from .dialog import AutoLedDialog
        board = pcbnew.GetBoard()
        dlg = AutoLedDialog(None, board)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
