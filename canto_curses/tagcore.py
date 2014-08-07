# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.rwlock import RWLock
from canto_next.hooks import call_hook

from .subthread import SubThread
from .config import config

import traceback
import logging

log = logging.getLogger("TAGCORE")

alltagcores = []

class TagCore(list):
    def __init__(self, tag):
        list.__init__(self)
        self.tag = tag
        self.changes = False
        self.lock = RWLock("lock: %s" % tag)
        alltagcores.append(self)

    # change functions must be called holding lock

    def ack_changes(self):
        self.changes = False

    def changed(self):
        self.changes = True

    def add_items(self, ids):
        self.lock.acquire_write()

        added = []
        for id in ids:
            self.append(id)
            added.append(id)

        call_hook("curses_items_added", [ self, added ] )

        self.changed()
        self.lock.release_write()

    def remove_items(self, ids):
        self.lock.acquire_write()

        removed = []

        # Copy self so we can remove from self
        # without screwing up iteration.

        for idx, id in enumerate(self[:]):
            if id in ids:
                log.debug("removing: %s" % (id,))

                list.remove(self, id)
                removed.append(id)

        call_hook("curses_items_removed", [ self, removed ] )

        self.changed()
        self.lock.release_write()

    # Remove all stories from this tag.

    def reset(self):
        self.lock.acquire_write()

        call_hook("curses_items_removed", [ self, self[:] ])
        del self[:]

        self.changed()
        self.lock.release_write()

class TagUpdater(SubThread):
    def init(self, backend):
        SubThread.init(self, backend)

        self.item_tag = None
        self.item_buf = []
        self.item_removes = []
        self.item_adds = []

        self.attributes = {}
        self.lock = RWLock("tagupdater")

        self.discard = False

        self.start_pthread()

        # Setup automatic attributes.

        # We know we're going to want at least these attributes for
        # all stories, as they're part of the fallback format string.

        self.needed_attrs = [ "title", "canto-state", "link", "enclosures" ]

        # Make sure we grab attributes needed for the story
        # format and story format.

        sfa = config.get_opt("story.format_attrs")
        tsa = config.get_opt("taglist.search_attributes")

        for attrlist in [ sfa, tsa ]:
            for sa in attrlist:
                if sa not in self.needed_attrs:
                    self.needed_attrs.append(sa)

        self.write("AUTOATTR", self.needed_attrs)

        strtags = config.get_var("strtags")

        # Request initial information, instantiate TagCores()

        self.write("WATCHTAGS", strtags)
        for tag in strtags:
            TagCore(tag)

    def prot_attributes(self, d):
        if self.discard:
            return

        # Update attributes, and then notify everyone to grab new content.
        self.lock.acquire_write()

        for key in d.keys():
            if key in self.attributes:

                # If we're updating, we want to create a whole new dict object
                # so that our stories dicts don't get updated without a sync

                cp = self.attributes[key].copy()
                cp.update(d[key])
                self.attributes[key] = cp
            else:
                self.attributes[key] = d[key]
        self.lock.release_write()

        call_hook("curses_attributes", [ self.attributes ])

    def prot_items(self, updates):
        if self.discard:
            return

        # Daemon should now only return with one tag in an items response

        tag = list(updates.keys())[0]

        if self.item_tag == None or self.item_tag.tag != tag:
            self.item_tag = None
            self.item_buf = []
            self.item_removes = []
            self.item_adds = []
            for have_tag in alltagcores:
                if have_tag.tag == tag:
                    self.item_tag = have_tag
                    break

            # Shouldn't happen
            else:
                return

        self.item_buf.extend(updates[tag])

        # Add new items.
        for id in updates[tag]:
            if id not in self.item_tag:
                self.item_adds.append(id)

    def prot_itemsdone(self, empty):
        unprotect = {"auto":[]}

        if self.item_tag == None:
            return

        if self.discard:
            self.item_tag = None
            self.item_buf = []
            self.item_removes = []
            self.item_adds = []
            return

        self.item_tag.add_items(self.item_adds)

        # Eliminate discarded items. This has to be done here, so we have
        # access to all of the items given in the multiple ITEM responses.

        protected = config.get_var("protected_ids")

        for id in self.item_tag:
            if id not in protected and id not in self.item_buf:
                self.item_removes.append(id)

        self.item_tag.remove_items(self.item_removes)

        for id in self.item_removes:
            unprotect["auto"].append(id)

        # If we're using the maintain update style, reorder the feed
        # properly. Append style requires no extra work (add_items does
        # it by default).

        conf = config.get_conf()

        if conf["update"]["style"] == "maintain":
            log.debug("Re-ordering items (update style maintain)")
            self.item_tag.reorder(self.item_buf)

        self.item_tag = None
        self.item_buf = []
        self.item_removes = []
        self.item_adds = []

        if unprotect["auto"]:
            self.write("UNPROTECT", unprotect)

    def prot_tagchange(self, tag):
        self.write("ITEMS", [ tag ])

    def prot_pong(self, args):
        self.discard=False

    # The following is the external interface to tagupdater.

    def update(self):
        strtags = config.get_var("strtags")
        for tag in strtags:
            self.write("ITEMS", [ tag ])

    def reset(self):
        self.lock.acquire_write()
        self.attributes = {}
        self.lock.release_write()

        for tag in alltagcores:
            tag.reset()
        self.write("PING", [])
        self.discard = True

    # Writes are already serialized, so in the meantime, we protect
    # self.attributes and self.needed_attrs with our lock.

    def get_attributes(self, id):
        r = {}
        self.lock.acquire_read()
        if id in self.attributes:
            r = self.attributes[id]
        self.lock.release_read()
        return r

    # This takes a fat argument because callers need to be able to curry
    # together multiple sets so stuff like 'item-state read *' don't generate
    # thousands of SETATTRIBUTES calls and take forever

    def set_attributes(self, arg):
        self.lock.acquire_write()
        self.write("SETATTRIBUTES", arg)
        self.lock.release_write()

    def request_attributes(self, id, attrs):
        self.write("ATTRIBUTES", { id : attrs })

    def need_attributes(self, id, attrs):
        self.lock.acquire_write()

        needed = self.needed_attrs[:]
        updated = False

        for attr in attrs:
            if attr not in needed:
                needed.append(attr)
                updated = True

        if updated:
            self.needed_attrs = needed
            self.write("AUTOATTR", self.needed_attrs)

        self.lock.release_write()

        # Even if we didn't update this time, make sure we attempt to get this
        # id's new needed attributes.

        self.write("ATTRIBUTES", { id : needed })

tag_updater = TagUpdater()
