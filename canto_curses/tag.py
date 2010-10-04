# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from theme import FakePad, WrapPad, theme_print
from story import Story

import logging
import curses

log = logging.getLogger("TAG")

# The Tag class manages stories. Externally, it looks
# like a Tag takes IDs from the backend and renders an ncurses pad. No class
# other than Tag actually touches Story objects directly.

class Tag(list):
    def __init__(self, tag, callbacks):
        list.__init__(self)

        # Note that Tag() is only given the top-level CantoCursesGui
        # callbacks as it shouldn't be doing input / refreshing
        # itself.

        self.callbacks = callbacks
        self.tag = tag

        # Upon creation, this Tag adds itself to the
        # list of all tags.

        callbacks["get_var"]("alltags").append(self)

    # We override eq so that empty tags don't evaluate
    # as equal and screw up things like enumeration.

    def __eq__(self, other):
        if self.tag != other.tag:
            return False
        return list.__eq__(self, other)

    # Create Story from ID before appending to list.

    def append(self, id):
        s = Story(id, self.callbacks)
        list.append(self, s)

    # Remove Story based on ID

    def remove(self, id):
        log.debug("removing: %s" % (id,))
        for item in self:
            if item.id == id:
                list.remove(self, item)

    def get_id(self, id):
        for item in self:
            if item.id == id:
                return item
        return None

    def get_ids(self):
        return [ s.id for s in self ]

    def refresh(self, mwidth, idx_offset):

        lines = self.render_header(mwidth, FakePad(mwidth))

        self.header_pad = curses.newpad(lines, mwidth)

        for i, item in enumerate(self):
            lines += item.refresh(mwidth, idx_offset + i)

        # Create a new pad with enough lines to
        # include all story objects.
        self.pad = curses.newpad(lines, mwidth)

        return self.render(mwidth, WrapPad(self.pad))

    def render_header(self, mwidth, pad):
        enumerated = self.callbacks["get_opt"]("taglist.tags_enumerated")
        header = self.tag + u"\n"
        if enumerated:
            curtags = self.callbacks["get_var"]("curtags")
            header = ("[%d] " % curtags.index(self)) + header

        lines = 0

        while header:
            header = theme_print(pad, header, mwidth, u"│", u"│")
            lines += 1

        return lines

    def render(self, mwidth, pad):
        # Update header_pad (used to float tag header)
        self.render_header(mwidth, WrapPad(self.header_pad))

        # Render to the taglist pad as well.
        spent_lines = self.render_header(mwidth, pad)
        mp = [spent_lines]

        for item in self:
            cur_lines = item.pad.getmaxyx()[0]
            mp.append(cur_lines)

            # Copy the item pad into the Tag's pad.
            item.pad.overwrite(self.pad, 0, 0, spent_lines, 0,\
                spent_lines + cur_lines - 1 , mwidth - 1)

            spent_lines += cur_lines

        # Return a list of integers, the heights of the header,
        # and all of the stories. The sum must == the height
        # of the tag's pad.
        return mp
