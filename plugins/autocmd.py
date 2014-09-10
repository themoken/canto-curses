# Autocmd Plugin
# by Jack Miller
# v1.0

# This plugin allows you to automatically do commands on canto-curses startup
# Useful for machine-specific or environment-specific configuration

# Commands should be added to this list.
# They should be single commands (i.e. no &)

cmds = []

# Examples

# Setting browser / browser_txt based on TERM

import os

if "DISPLAY" not in os.environ:
    cmds.append("browser = elinks")
    cmds.append("txt_browser = True")
else:
    cmds.append("browser = firefox")
    cmds.append("txt_browser = False")

# The actual plugin workings below.

from canto_curses.gui import GuiPlugin
from canto_next.hooks import on_hook

class AutoCmdGui(GuiPlugin):
    def __init__(self, gui):
        self.plugin_attrs = {}
        self.gui = gui

        on_hook("curses_start", self.do_cmds)

    def do_cmds(self):
        for cmd in cmds:
            self.gui.issue_cmd(cmd)
