# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.hooks import on_hook, remove_hook

from .parser import prep_for_display
from .html import htmlparser
from .text import TextBox
from .tagcore import tag_updater

import logging
import re

log = logging.getLogger("READER")

class ReaderPlugin(Plugin):
    pass

class Reader(TextBox):
    def __init__(self):
        TextBox.__init__(self)

        self.plugin_class = ReaderPlugin
        self.update_plugin_lookups()

    def init(self, pad, callbacks):
        TextBox.init(self, pad, callbacks)

        self.quote_rgx = re.compile("[\\\"](.*?)[\\\"]")
        on_hook("curses_opt_change", self.on_opt_change)
        on_hook("curses_var_change", self.on_var_change)

    def die(self):
        remove_hook("curses_opt_change", self.on_opt_change)
        remove_hook("curses_var_change", self.on_var_change)

    def on_opt_change(self, change):
        if "reader" not in change:
            return

        if "show_description" in change["reader"] or\
                "enumerate_links" in change["reader"]:
            self.callbacks["set_var"]("needs_refresh", True)
            self.callbacks["release_gui"]()

    def on_attributes(self, attributes):
        sel = self.callbacks["get_var"]("reader_item")
        if sel and sel.id in attributes:
            remove_hook("curses_attributes", self.on_attributes)
            self.callbacks["set_var"]("needs_refresh", True)
            self.callbacks["release_gui"]()

    def on_var_change(self, variables):
        # If we've been instantiated and unfocused, and selection changes,
        # we need to be redrawn.

        if "selected" in variables and variables["selected"]:
            self.callbacks["set_var"]("reader_item", variables["selected"])
            self.callbacks["set_var"]("needs_refresh", True)
            self.callbacks["release_gui"]()

    def update_text(self):
        reader_conf = self.callbacks["get_opt"]("reader")

        s = "No selected story.\n"

        sel = self.callbacks["get_var"]("reader_item")
        if sel:
            self.links = [("link",sel.content["link"],"mainlink")]

            s = "%1%B" + prep_for_display(sel.content["title"]) + "%b\n"

            # Make sure the story has the most recent info before we check it.
            sel.sync()

            # We use the description for most reader content, so if it hasn't
            # been fetched yet then grab that from the server now and setup
            # a hook to get notified when sel's attributes are changed.

            if "description" not in sel.content\
                    and "content" not in sel.content:
                tag_updater.request_attributes(sel.id, ["description", "content"])
                s += "%BWaiting for content...%b\n"
                on_hook("curses_attributes", self.on_attributes)
            else:

                # Add enclosures before HTML parsing so that we can add a link
                # and have the remaining link logic pick it up as normal.

                extra_content = ""

                if reader_conf['show_enclosures']:
                    for enc in sel.content["enclosures"]:
                        # No point in enclosures without links
                        if "href" not in enc:
                            continue

                        if "type" not in enc:
                            enc["type"] = "unknown"

                        if not extra_content:
                            extra_content = "\n\n"

                        extra_content += "<a href=\""
                        extra_content += enc["href"]
                        extra_content += "\">("
                        extra_content += enc["type"]
                        extra_content += ")</a>\n"

                # Grab text content over description, as it's likely got more
                # information.

                mainbody = sel.content["description"]
                if "content" in sel.content:
                    for c in sel.content["content"]:
                        if "type" in c and "text" in c["type"]:
                            mainbody = c["value"]

                # This needn't be prep_for_display'd because the HTML parser
                # handles that.

                content, links = htmlparser.convert(mainbody + extra_content)

                # 0 always is the mainlink, append other links
                # to the list.

                self.links += links

                if reader_conf['show_description']:
                    s += self.quote_rgx.sub("%6\"\\1\"%0", content)

                if reader_conf['enumerate_links']:
                    s += "\n\n"

                    for idx, (t, url, text) in enumerate(self.links):
                        text = prep_for_display(text)
                        url = prep_for_display(url)

                        link_text = "[%B" + str(idx) + "%b][" +\
                                text + "]: " + url + "\n\n"

                        if t == "link":
                            link_text = "%5" + link_text + "%0"
                        elif t == "image":
                            link_text = "%4" + link_text + "%0"

                        s += link_text

        # After we have generated the entirety of the content,
        # strip out any egregious spacing.

        self.text = s.rstrip(" \t\v\n")

    def cmd_goto(self, **kwargs):
        # link = ( type, url, text )
        links = [ l[1] for l in kwargs["links"] ]
        self._goto(links)

    def cmd_fetch(self, **kwargs):
        # link = ( type, url, text )
        links = [ l[1] for l in kwargs["links"] ]
        self._fetch(links)

    def cmd_destroy(self, **kwargs):
        self.callbacks["set_var"]("reader_item", None)
        self.callbacks["die"](self)

    def get_opt_name(self):
        return "reader"
