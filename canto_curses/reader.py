# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from canto_next.hooks import on_hook, remove_hook, unhook_all

from .command import register_commands, register_arg_types, unregister_all, _int_range
from .theme import prep_for_display
from .html import htmlparser
from .text import TextBox
from .tagcore import tag_updater
from .color import cc

import traceback
import logging
import re

log = logging.getLogger("READER")

class ReaderPlugin(Plugin):
    pass

class Reader(TextBox):
    def init(self, pad, callbacks):
        TextBox.init(self, pad, callbacks)

        self.quote_rgx = re.compile("[\\\"](.*?)[\\\"]")
        on_hook("curses_opt_change", self.on_opt_change, self)
        on_hook("curses_var_change", self.on_var_change, self)

        args = {
            "link-list" : ("", self.type_link_list),
        }

        cmds = {
            "goto" : (self.cmd_goto, ["link-list"], "Goto a specific link"),
            "destroy" : (self.cmd_destroy, [], "Destroy this window"),
            "show-links" : (self.cmd_show_links, [], "Toggle link list display"),
            "show-summary" : (self.cmd_show_desc, [], "Toggle summary display"),
            "show-enclosures" : (self.cmd_show_encs, [], "Toggle enclosure list display")
        }

        register_arg_types(self, args)
        register_commands(self, cmds, "Reader")

        self.plugin_class = ReaderPlugin
        self.update_plugin_lookups()

    def die(self):
        unhook_all(self)
        unregister_all(self)

    def on_opt_change(self, change):
        if "reader" not in change:
            return

        for opt in ["show_description", "enumerate_links", "show_enclosures"]:
            if opt in change["reader"]:
                self.callbacks["set_var"]("needs_refresh", True)
                self.callbacks["release_gui"]()
                return

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

    def type_link_list(self):
        domains = { 'all' : self.links }
        syms = { 'all' : { '*' : range(0, len(self.links)) } }

        fallback = []
        if len(self.links):
            fallback = [ self.links[0] ]

        return (None, lambda x:_int_range("link", domains, syms, fallback, x))

    def update_text(self):
        reader_conf = self.callbacks["get_opt"]("reader")

        s = "No selected story.\n"
        extra_content = ""

        sel = self.callbacks["get_var"]("reader_item")
        if sel:
            self.links = [("link",sel.content["link"],"mainlink")]

            s = "%B" + prep_for_display(sel.content["title"]) + "%b\n"

            # Make sure the story has the most recent info before we check it.
            sel.sync()

            # We use the description for most reader content, so if it hasn't
            # been fetched yet then grab that from the server now and setup
            # a hook to get notified when sel's attributes are changed.

            l = ["description", "content", "links", "media_content",
                    "enclosures"]

            for attr in l:
                if attr not in sel.content:
                    tag_updater.request_attributes(sel.id, l)
                    s += "%BWaiting for content...%b\n"
                    on_hook("curses_attributes", self.on_attributes, self)
                    break
            else:
                # Grab text content over description, as it's likely got more
                # information.

                mainbody = sel.content["description"]
                if "content" in sel.content:
                    for c in sel.content["content"]:
                        if "type" in c and "text" in c["type"]:
                            mainbody = c["value"]

                # Add enclosures before HTML parsing so that we can add a link
                # and have the remaining link logic pick it up as normal.

                if reader_conf['show_enclosures']:
                    parsed_enclosures = []

                    if sel.content["links"]:
                        for lnk in sel.content["links"]:
                            if 'rel' in lnk and 'href' in lnk and lnk['rel'] == 'enclosure':
                                if 'type' not in lnk:
                                    lnk['type'] = 'unknown'
                                parsed_enclosures.append((lnk['href'], lnk['type']))

                    if sel.content["media_content"] and 'href' in sel.content["media_content"]:
                        if 'type' not in sel.content["media_content"]:
                            sel.content['media_content']['type'] = 'unknown'
                        parsed_enclosures.append((sel.content["media_content"]['href'],\
                                    sel.content["media_content"]['type']))

                    if sel.content["enclosures"] and 'href' in sel.content["enclosures"]:
                        if 'type' not in sel.content["enclosures"]:
                            sel.content['enclosures']['type'] = 'unknown'
                        parsed_enclosures.append((sel.content['enclosures']['href'],\
                                    sel.content['enclosures']['type']))

                    if not parsed_enclosures:
                        mainbody += "<br />[ No enclosures. ]<br />"
                    else:
                        for lnk, typ in parsed_enclosures:
                            mainbody += "<a href=\""
                            mainbody += lnk
                            mainbody += "\">["
                            mainbody += typ
                            mainbody += "]</a>\n"

                for attr in list(self.plugin_attrs.keys()):
                    if not attr.startswith("edit_"):
                        continue
                    try:
                        a = getattr(self, attr)
                        (mainbody, extra_content) = a(mainbody, extra_content)
                    except:
                        log.error("Error running Reader edit plugin")
                        log.error(traceback.format_exc())

                # This needn't be prep_for_display'd because the HTML parser
                # handles that.

                content, links = htmlparser.convert(mainbody)

                # 0 always is the mainlink, append other links
                # to the list.

                self.links += links

                if reader_conf['show_description']:
                    s += self.quote_rgx.sub(cc("reader_quote") + "\"\\1\"" + cc.end("reader_quote"), content)

                if reader_conf['enumerate_links']:
                    s += "\n\n"

                    for idx, (t, url, text) in enumerate(self.links):
                        text = prep_for_display(text)
                        url = prep_for_display(url)

                        link_text = "[%B" + str(idx) + "%b][" +\
                                text + "]: " + url + "\n\n"

                        if t == "link":
                            link_text = cc("reader_link") + link_text + cc.end("reader_link")
                        elif t == "image":
                            link_text = cc("reader_image_link") + link_text + cc.end("reader_image_link")

                        s += link_text

        # After we have generated the entirety of the content,
        # strip out any egregious spacing.

        self.text = s.rstrip(" \t\v\n") + extra_content

    def cmd_goto(self, links):
        # link = ( type, url, text )
        hrefs = [ l[1] for l in links ]
        self._goto(hrefs)

    def _toggle_cmd(self, opt):
        c = self.callbacks["get_conf"]()
        c["reader"][opt] = not c["reader"][opt]
        self.callbacks["set_conf"](c)

    def cmd_show_links(self):
        self._toggle_cmd("enumerate_links")

    def cmd_show_desc(self):
        self._toggle_cmd("show_description")

    def cmd_show_encs(self):
        self._toggle_cmd("show_enclosures")

    def cmd_destroy(self):
        self.callbacks["set_var"]("reader_item", None)
        self.callbacks["die"](self)

    def get_opt_name(self):
        return "reader"
