# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.hooks import on_hook, remove_hook

from parser import prep_for_display
from command import command_format
from html import htmlparser
from text import TextBox

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

        self.quote_rgx = re.compile(u"[\\\"](.*?)[\\\"]")
        on_hook("opt_change", self.on_opt_change)

    def die(self):
        remove_hook("opt_change", self.on_opt_change)

    def on_opt_change(self, change):
        if "reader" not in change:
            return

        if "show_description" in change["reader"] or\
                "enumerate_links" in change["reader"]:
            self.refresh()

    def on_attributes(self, attributes):
        sel = self.callbacks["get_var"]("reader_item")
        if sel in attributes:
            remove_hook("attributes", self.on_attributes)

            # Don't bother checking attributes. If we're still
            # lacking, refresh  will re-enable this hook

            self.refresh()

    def update_text(self):
        reader_conf = self.callbacks["get_opt"]("reader")

        s = "No selected story.\n"

        sel = self.callbacks["get_var"]("reader_item")
        if sel:
            self.links = [("link",sel.content["link"],"mainlink")]

            s = "%1%B" + prep_for_display(sel.content["title"]) + "%b\n"

            # We use the description for most reader content, so if it hasn't
            # been fetched yet then grab that from the server now and setup
            # a hook to get notified when sel's attributes are changed.

            if "description" not in sel.content:
                self.callbacks["write"]("ATTRIBUTES",\
                        { sel.id : ["description" ] })
                s += "%BWaiting for content...%b\n"
                on_hook("attributes", self.on_attributes)
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

                content, links =\
                        htmlparser.convert(sel.content["description"] +\
                            extra_content)

                # 0 always is the mainlink, append other links
                # to the list.

                self.links += links

                if reader_conf['show_description']:
                    s += self.quote_rgx.sub(u"%6\"\\1\"%0", content)

                if reader_conf['enumerate_links']:
                    s += "\n\n"

                    for idx, (t, url, text) in enumerate(self.links):
                        text = prep_for_display(text)
                        url = prep_for_display(url)

                        link_text = "[%B" + unicode(idx) + "%b][" +\
                                text + "]: " + url + "\n\n"

                        if t == "link":
                            link_text = "%5" + link_text + "%0"
                        elif t == "image":
                            link_text = "%4" + link_text + "%0"

                        s += link_text

        # After we have generated the entirety of the content,
        # strip out any egregious spacing.

        self.text = s.rstrip(" \t\v\n")

    def eprompt(self, prompt):
        return self._cfg_set_prompt("reader.enumerate_links", "links: ")

    def listof_links(self, args):
        ints = self._listof_int(args, 0, len(self.links),\
                lambda : self.eprompt("links: "))
        return (True, [ self.links[i] for i in ints ], "")

    @command_format([("links", "listof_links")])
    def cmd_goto(self, **kwargs):
        # link = ( type, url, text )
        links = [ l[1] for l in kwargs["links"] ]
        self._goto(links)

    @command_format([("links", "listof_links")])
    def cmd_fetch(self, **kwargs):
        # link = ( type, url, text )
        links = [ l[1] for l in kwargs["links"] ]
        self._fetch(links)

    def get_opt_name(self):
        return "reader"
