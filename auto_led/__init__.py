"""KiCad AutoLED: place LEDs on a shape taken from an SVG / PNG / BMP image."""

try:
    import pcbnew  # noqa: F401
except ImportError:  # imported outside KiCad (command line / tests)
    pcbnew = None


def _inside_kicad_gui():
    try:
        import wx
    except ImportError:
        return False
    return wx.GetApp() is not None


if pcbnew is not None and _inside_kicad_gui():
    from .plugin import AutoLedPlugin
    try:
        AutoLedPlugin().register()
    except SystemError:
        pass  # a wx app outside KiCad (scripts / tests): nothing to register with
