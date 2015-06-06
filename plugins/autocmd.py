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
    cmds.append("set browser elinks")
    cmds.append("set browser.text True")
else:
    cmds.append("set browser firefox")
    cmds.append("set browser.text False")

# The actual plugin workings below.

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.gui import GuiPlugin
from canto_next.hooks import on_hook

class AutoCmdGui(GuiPlugin):
    def __init__(self, gui):
        self.plugin_attrs = {}
        self.gui = gui

        on_hook("curses_start", self.do_cmds)

    def do_cmds(self):
        self.gui.callbacks["set_var"]("quiet", True)
        for cmd in cmds:
            self.gui.issue_cmd(cmd)
        self.gui.callbacks["set_var"]("quiet", False)
