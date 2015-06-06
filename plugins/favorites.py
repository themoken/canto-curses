# Favorite Plugin
# by Jack Miller
# v1.0

# This plugin allows certain items to be tagged as 'user:favorite' and then a
# custom style to be applied to those items.

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.taglist import TagListPlugin
from canto_curses.story import StoryPlugin
from canto_curses.command import register_commands

class StoryFavorite(StoryPlugin):
    def __init__(self, story):
        self.plugin_attrs = {}
        story.pre_format += "%?{'user:favorite' in ut}(*:)"

class TagListFavorite(TagListPlugin):
    def __init__(self, taglist):
        self.plugin_attrs = {}

        cmds = {
            "favorite" : (self.cmd_favorite, ["item-list"], "Favorite items."),
        }
        register_commands(taglist, cmds)

        self.taglist = taglist

        taglist.bind('*', 'favorite')

    def cmd_favorite(self, items):
        self.taglist.cmd_tag_item('%favorite', items)
