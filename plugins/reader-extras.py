# Reader extras
# by Jack Miller
# v1.0

# Designed to put extra interesting content in the reader output.

enabled_extras = ['datetime', 'slashdot', 'authors']

hacks = {}

datetime_attrs = [ 'published_parsed', 'updated_parsed' ]

def datetime_extras(body, extra_content, attrs):
    import time

    if attrs['published_parsed']:
        body = "Published: " + time.asctime(tuple(attrs['published_parsed'])) + "<br />" + body
    elif attrs['updated_parsed']:
        body = "Updated: " + time.asctime(tuple(attrs['updated_parsed'])) + "<br />" + body

    return (body, extra_content)

hacks['datetime'] = ('.*', datetime_attrs, datetime_extras)

# Slashdot (example)

slashdot_attrs = [ 'slash_department' ]

def slashdot_extras(body, extra_content, attrs):
    dept = "From the <strong>%s</strong> department<br />" % attrs["slash_department"]
    return (dept + body, extra_content)

hacks['slashdot'] = ('.*slashdot\\.org.*', slashdot_attrs, slashdot_extras)

# Authors (example)

authors_attrs = [ 'author' ]

def authors_extras(body, extra_content, attrs):
    # Requested attributes will always be in attrs, but they may be empty
    # The daemon returns "" for unknown attributes.

    if attrs['author']:
        return (body + ("<br />By: <strong>%s</strong><br />" % attrs['author']), extra_content)
    return (body, extra_content)

hacks['authors'] = ('.*', authors_attrs, authors_extras)

# If you turn on DEBUG_CONTENT, an entire item and all of its content will be
# appended to the Reader output, to let you look at what is available in an
# item.

DEBUG_CONTENT = False

from canto_next.plugins import check_program

check_program("canto-curses")

from canto_next.hooks import on_hook, remove_hook
from canto_curses.reader import ReaderPlugin
from canto_curses.tagcore import tag_updater
from canto_curses.theme import prep_for_display
import pprint
import re

import logging

log = logging.getLogger("EXTRAS")

class ReaderExtrasPlugin(ReaderPlugin):
    def __init__(self, reader):
        self.plugin_attrs = {'edit_extras' : self.edit_extras}
        if DEBUG_CONTENT:
            self.plugin_attrs['edit_debug'] = self.edit_debug

        self.reader = reader
        self.got_attrs = False
        self.needed_attrs = []
        self.do_funcs = []
        self.setup_hook = False

        # Convert enabled extras' URL regexen into re objects once so we don't
        # convert them all on eval() and we don't have to throw exceptions when
        # we're actually running.

        for extra in enabled_extras:
            hacks[extra] = (re.compile(hacks[extra][0]),) + hacks[extra][1:]

    def on_attributes(self, attributes):
        sel = self.reader.callbacks["get_var"]("reader_item")
        if sel and sel.id in attributes:
            # Sucks that we have to check these, but we can't be sure
            # any particular call is ours.
            for attr in self.needed_attrs:
                if attr not in attributes[sel.id]:
                    break
            else:
                remove_hook("curses_attributes", self.on_attributes)
                self.got_attrs = True
                self.reader.callbacks["set_var"]("needs_refresh", True)
                self.reader.callbacks["release_gui"]()

    def _dofuncs(self, body, extra_content, sel):
        for f in self.do_funcs:
            body, extra_content = f(body, extra_content, sel.content)
        return (body, extra_content)

    def edit_extras(self, body, extra_content):
        sel = self.reader.callbacks["get_var"]("reader_item")
        if not sel:
            return

        # If we have the attrs, or are already waiting, bail.
        if self.got_attrs:
            return self._dofuncs(body, extra_content, sel)
        elif self.setup_hook:
            return (body, extra_content)

        item_url = eval(sel.id)["URL"]

        for extra in enabled_extras:
            url_rgx, needed, func = hacks[extra]
            if url_rgx.match(item_url):
                for a in needed:
                    if a not in sel.content and a not in self.needed_attrs:
                        self.needed_attrs.append(a)
                self.do_funcs.append(func)

        if self.needed_attrs != []:
            on_hook("curses_attributes", self.on_attributes)
            tag_updater.request_attributes(sel.id, self.needed_attrs)
            self.setup_hook = True
            return (body, extra_content)
        else:
            self.got_attrs = True
            return self._dofuncs(body, extra_content, sel)

    # Body is sent through the HTML process, so HTML formatting will be allowed
    # and link tags will be used by goto et. al

    # Extra content is naturally formatted text that may have canto theme escapes

    def edit_debug(self, body, extra_content):
        sel = self.reader.callbacks["get_var"]("reader_item")
        if not sel:
            return

        if not self.got_attrs:
            on_hook("curses_attributes", self.on_attributes)
            tag_updater.request_attributes(sel.id, [])
        else:
            extra_content += '\n\n'
            for k in sel.content.keys():
                line = '[%s]: %s' % (k, sel.content[k])
                extra_content += prep_for_display(line) + '\n'

        return(body, extra_content)
