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

# Also included, the option to forcibly remove anything that looks like HTML.
# Useful for cleaning horribly formatted feeds, but possibly destructive of
# good content wrapped in <>. Set this to True to enable.

NO_HTML_EVER = False

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_curses.story import StoryPlugin

# From kjellgren (canto-curses issue #18)

def remove_html_markup(s):
    tag = False
    quote = False
    out = ""
    for c in s:
        if c == '<' and not quote:
            tag = True
        elif c == '>' and not quote:
            tag = False
        elif (c == '"' or c == "'") and tag:
            quote = not quote
        elif not tag:
            out = out + c
    return out

class CleanTitle(StoryPlugin):
    def __init__(self, story):
        self.story = story
        self.plugin_attrs = { "edit_clean" : self.edit_clean }

    def edit_clean(self):
        t = self.story.content["title"]

        for o,n in replacements:
            t = t.replace(o, n)

        if NO_HTML_EVER:
            t = remove_html_markup(t)

        self.story.content["title"] = t
