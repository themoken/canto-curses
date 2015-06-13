# Canto Default Theme

# Defined as a plugin to use as a base for other themes.

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.story import StoryPlugin
from canto_curses.tag import TagPlugin
from canto_curses.theme import prep_for_display
from canto_curses.color import cc

class CantoThemeStoryDefault(StoryPlugin):
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

class CantoThemeTagDefault(TagPlugin):
    def __init__(self, tag):
        self.tag = tag
        self.plugin_attrs = { "eval" : self.eval }

    def eval(self):
        tag = self.tag

        # Make sure to strip out the category from category:name
        str_tag = tag.tag.split(':', 1)[1]

        unread = len([s for s in tag\
                if "canto-state" not in s.content or\
                "read" not in s.content["canto-state"]])

        s = ""

        if tag.selected:
            s += cc("selected")

        if tag.collapsed:
            s += "[+]"
        else:
            s += "[-]"

        s += " " + str_tag + " "

        s += "[" + cc("unread") + str(unread) + cc.end("unread") + "]"

        if tag.updates_pending:
            s += " [" + cc("pending") + str(tag.updates_pending) + cc.end("pending") + "]"

        if tag.selected:
            s += cc.end("selected")

        return s

