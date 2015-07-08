# Clean Title Plugin
# by Jack Miller
# v1.0

# This plugin will strip some annoying content out of story titles. Even though
# most of it should technically still be in there (we already try to parse
# HTML, etc.) some feeds are poorly defined and will double escape HTML and
# insert annoying newlines.

# For now, just do a simple string replace, regexen are probably a bit heavy
# for this.

replacements = [
    ("\n", ""),
    ("<em>",""),
    ("</em>",""),
    ("<strong>",""),
    ("</strong>",""),
    ("<nobr />", ""),
]

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.story import StoryPlugin

class CleanTitle(StoryPlugin):
    def __init__(self, story):
        self.story = story
        self.plugin_attrs = { "edit_clean" : self.edit_clean }

    def edit_clean(self):
        t = self.story.content["title"]

        for o,n in replacements:
            t = t.replace(o, n)

        self.story.content["title"] = t
