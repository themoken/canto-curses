# Yank Plugin
# by Jack Miller
# v1.0

# Requires xclip to be somewhere in $PATH

from canto_curses.taglist import TagListPlugin
from canto_curses.reader import ReaderPlugin
from canto_curses.command import command_format

from os import system
import logging
import traceback

log = logging.getLogger("YANK")

def yank(content):
    system('echo -n %s | xclip' % (content,))

class TagListYank(TagListPlugin):
    def __init__(self):
        self.plugin_attrs = {
            "cmd_yank_link" : self.cmd_yank_link,
            "cmd_yank_title" : self.cmd_yank_title,
        }

    @command_format([("item","sel_or_item")])
    def cmd_yank_link(self, taglist, **kwargs):
        yank(kwargs["item"].content["link"])
        
    @command_format([("item","sel_or_item")])
    def cmd_yank_title(self, taglist, **kwargs):
        yank(kwargs["item"].content["title"])
        
class ReaderYank(ReaderPlugin):
    def __init__(self):
        self.plugin_attrs = {
            "cmd_yank_link" : self.cmd_yank_link,
            "cmd_yank_title" : self.cmd_yank_title,
        }

    @command_format([("links","listof_links")])
    def cmd_yank_link(self, reader, **kwargs):
        for link in kwargs["links"]:
            yank(link[1])
        
    @command_format([])
    def cmd_yank_title(self, reader, **kwargs):
        item = reader.callbacks["get_var"]("reader_item")
        yank(item.content["title"])
