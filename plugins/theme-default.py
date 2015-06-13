# Canto Default Theme

# Defined as a plugin to use as a base for other themes.

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.story import StoryPlugin
from canto_curses.theme import prep_for_display
from canto_curses.color import cc

class CantoThemeDefault(StoryPlugin):
    def __init__(self, story):
        self.story = story
        self.plugin_attrs = { "eval" : self.eval }

    def eval(self):
        story = self.story
        s = ""

        if "read" in story.content["canto-state"]:
            s += cc("read")
        else:
            s += cc("unread")

        if story.marked:
            s += cc("marked") + "[*]"

        if story.selected:
            s += cc("selected")

        s += prep_for_display(story.content["title"])

        if story.selected:
            s += cc.end("selected")

        if story.marked:
            s += cc.end("marked")

        if "read" in story.content["canto-state"]:
            s += cc.end("read")
        else:
            s += cc.end("unread")

        return s
