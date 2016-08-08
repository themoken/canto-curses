# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2016 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.rwlock import RWLock
from canto_next.hooks import call_hook, on_hook

from .subthread import SubThread
from .locks import config_lock
from .config import config, story_needed_attrs

import traceback
import logging

log = logging.getLogger("TAGCORE")

alltagcores = []

class TagCore(list):
    def __init__(self, tag):
        list.__init__(self)
        self.tag = tag

        self.changes = False
        self.was_reset = False

        self.lock = RWLock("lock: %s" % tag)
        alltagcores.append(self)

    # change functions must be called holding lock

    def ack_changes(self):
        self.changes = False

    def changed(self):
        self.changes = True

    def set_items(self, ids):
        self.lock.acquire_write()

        del self[:]
        self.extend(ids)
        self.changed()

        self.lock.release_write()

class TagUpdater(SubThread):
    def init(self, backend):
        SubThread.init(self, backend)

        self.updating = []

        self.attributes = {}
        self.lock = RWLock("tagupdater")

        self.start_pthread()

        # Setup automatic attributes.

        # We know we're going to want at least these attributes for
        # all stories, as they're part of the fallback format string.

        self.needed_attrs = [ "title", "canto-state", "canto-tags", "link", "enclosures" ]

        tsa = config.get_opt("taglist.search_attributes")

        for attrlist in [ story_needed_attrs, tsa ]:
            for sa in attrlist:
                if sa not in self.needed_attrs:
                    self.needed_attrs.append(sa)

        self.write("AUTOATTR", self.needed_attrs)

        # Lock config_lock so that strtags doesn't change and we miss
        # tags.

        config_lock.acquire_read()

        strtags = config.get_var("strtags")

        # Request initial information, instantiate TagCores()

        self.write("WATCHTAGS", strtags)
        for tag in strtags:
            self.on_new_tag(tag)

        on_hook("curses_new_tag", self.on_new_tag)
        on_hook("curses_del_tag", self.on_del_tag)
        on_hook("curses_stories_removed", self.on_stories_removed)
        on_hook("curses_def_opt_change", self.on_def_opt_change)

        config_lock.release_read()

    def on_new_tag(self, tag):
        self.write("WATCHTAGS", [ tag ])
        self.prot_tagchange(tag)
        call_hook("curses_new_tagcore", [ TagCore(tag) ])

    def on_del_tag(self, tag):
        for tagcore in alltagcores[:]:
            if tagcore.tag == tag:
                if len(tagcore):
                    call_hook("curses_items_removed", [ tagcore, tagcore ] )
                    tagcore.set_items([])
                call_hook("curses_del_tagcore", [ tagcore ])
                alltagcores.remove(tagcore)
                while tagcore in self.updating:
                    self.updating.remove(tagcore)
                return

    # Once they've been removed from the GUI, their attributes can be forgotten
    def on_stories_removed(self, tag, items):
        tagcore = None
        for tc in alltagcores:
            if tc.tag == tag.tag:
                tagcore = tc
                break
        else:
            log.warn("Couldn't find tagcore for removed story tag %s" % tag.tag)

        self.lock.acquire_write()
        for item in items:
            if tagcore and item.id in tc:
                log.debug("%s still in tagcore, not removing", item.id)
                continue
            if item.id in self.attributes:
                del self.attributes[item.id]
        self.lock.release_write()

    # Changes to global filters should force a full refresh.

    def on_def_opt_change(self, defaults):
        if 'global_transform' in defaults:
            log.debug("global_transform changed, forcing reset + update")
            self.update()

    def prot_attributes(self, d):
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
        # Daemon should now only return with one tag in an items response

        tag = list(updates.keys())[0]

        for have_tag in alltagcores:
            if have_tag.tag == tag:
                break
        else:
            return

        sorted_updated_ids = list(enumerate(updates[tag]))
        sorted_updated_ids.sort(key=lambda x : x[1])

        sorted_current_ids = list(enumerate(have_tag))
        sorted_current_ids.sort(key=lambda x : x[1])

        new_ids = []
        cur_ids = []
        old_ids = []

        for c_place, c_id in sorted_current_ids:
            while sorted_updated_ids and c_id > sorted_updated_ids[0][1]:
                new_ids.append(sorted_updated_ids.pop(0))

            if not sorted_updated_ids or c_id < sorted_updated_ids[0][1]:
                old_ids.append(c_id)
            else:
                cur_ids.append(sorted_updated_ids.pop(0))

        new_ids += sorted_updated_ids

        all_ids = new_ids + cur_ids
        all_ids.sort()

        have_tag.set_items([x[1] for x in all_ids])

        if new_ids:
            call_hook("curses_items_added", [ have_tag, [x[1] for x in new_ids] ] )

        if old_ids:
            call_hook("curses_items_removed", [ have_tag, old_ids ] )

        if have_tag in self.updating:
            have_tag.was_reset = True
            call_hook("curses_tag_updated", [ have_tag ])
            self.updating.remove(have_tag)
            if self.updating == []:
                call_hook("curses_update_complete", [])

    def prot_itemsdone(self, tag):
        pass

    def prot_tagchange(self, tag):
        self.write("ITEMS", [ tag ])

    # The following is the external interface to tagupdater.

    def update(self):
        self.reset()
        strtags = config.get_var("strtags")
        for tag in strtags:
            self.write("ITEMS", [ tag ])

    def reset(self):
        self.updating += alltagcores
        return True

    def transform(self, name, transform):
        self.write("TRANSFORM", { name : transform })
        self.reset()

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
