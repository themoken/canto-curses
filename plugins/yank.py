# Yank Plugin
# by Jack Miller
# v1.1

# Requires xclip to be somewhere in $PATH

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.taglist import TagListPlugin
from canto_curses.command import register_commands

from subprocess import Popen, PIPE
from os import system
import logging

log = logging.getLogger("YANK")

def yank(content):
    p = Popen(["xclip"], stdin=PIPE)
    p.communicate(content.encode("utf-8"))

class TagListYank(TagListPlugin):
    def __init__(self, taglist):
        self.plugin_attrs = {}

        cmds = {
            "yank-link" : (self.cmd_yank_link, ["item-list"], "Yank link"),
            "yank-title" : (self.cmd_yank_title, ["item-list"], "Yank title"),
        }
        register_commands(taglist, cmds)

        taglist.bind('y', 'yank-link')
        taglist.bind('Y', 'yank-title')

    def cmd_yank_link(self, items):
        yank(items[0].content["link"])

    def cmd_yank_title(self, items):
        yank(items[0].content["title"])
