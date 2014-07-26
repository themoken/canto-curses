# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

# The CantoCursesConfig object is a self contained class that it responsible
# for getting a connection to the daemon, getting its configuration settings
# (opts), validating them, and making it (and updates) convenient to use.

# It also contain psuedo-configuration (vars) that aren't actually written to
# the config, but still need to be accessed from various code. These are mostly
# for restoring the screen after a refresh.

# By necessity, it also functions as the thread that watches for added /
# deleted tags, but not for changes to existing tags.

from canto_next.hooks import call_hook
from canto_next.rwlock import RWLock, write_lock, read_lock
from canto_next.remote import assign_to_dict, access_dict

DEFAULT_FSTRING = "%[1]%?{en}([%i] :)%?{ren}([%x] :)%?{sel}(%{selected}:%{unselected})%?{rd}(%{read}:%{unread})%?{m}(%{marked}:%{unmarked})%t%?{m}(%{marked_end}:%{unmarked_end})%?{rd}(%{read_end}:%{unread_end})%?{sel}(%{selected_end}:%{unselected_end})%0"

DEFAULT_TAG_FSTRING = "%[1]%?{sel}(%{selected}:%{unselected})%?{c}([+]:[-])%?{en}([%{to}]:)%?{aen}([%{vto}]:) %t [%B%2%n%1%b]%?{sel}(%{selected_end}:%{unselected_end})%0"

from .locks import config_lock, var_lock
from .subthread import SubThread

from threading import Thread
import traceback
import logging
import curses   # Colors
import re       # 'tags' setting is a regex

log = logging.getLogger("CONFIG")

class CantoCursesConfig(SubThread):

    # No __init__ because we want this to be global, but init must be called
    # with a connection to the daemon, so we call .init() manually.

    def init(self, backend):
        SubThread.init(self, backend)

        self.initd = False

        self.vars = {
            "location" : backend.location_args,
            "error_msg" : "No error.",
            "info_msg" : "No info.",
            "input_prompt" : "",
            "input_completion_root" : None,
            "input_completions" : [],
            "reader_item" : None,
            "reader_offset" : 0,
            "errorbox_offset" : 0,
            "infobox_offset" : 0,
            "selected" : None,
            "old_selected" : None,
            "old_toffset" : 0,
            "target_obj" : None,
            "target_offset" : 0,
            "strtags" : [],
            "curtags" : [],
            "alltags" : [],
            "needs_refresh" : False,
            "needs_redraw" : False,
            "needs_resize" : False,
            "protected_ids" : [],
            "transforms" : [],
            "taglist_visible_tags" : [],
        }

        self.keys = {
            ":" : "command",
            "q" : "quit"
        }

        self.validators = {
            "browser" :
            {
                "path" : self.validate_string,
                "text" : self.validate_bool,
            },

            "tags" : self.validate_tags,
            "tagorder" : self.validate_tag_order,

            "tag" :
            {
                "format" : self.validate_string,
                "selected" : self.validate_string,
                "unselected" : self.validate_string,
                "selected_end" : self.validate_string,
                "unselected_end" : self.validate_string,
            },

            "update" :
            {
                "style" : self.validate_update_style,
                "auto" :
                {
                    "interval" : self.validate_uint,
                    "enabled" : self.validate_bool,
                }
            },

            "reader" :
            {
                "window" : self.validate_window,
                "key" : self.validate_key,
                "enumerate_links" : self.validate_bool,
                "show_description" : self.validate_bool,
                "show_enclosures" : self.validate_bool,
            },

            "taglist" :
            {
                "window" : self.validate_window,
                "key" : self.validate_key,
                "tags_enumerated" : self.validate_bool,
                "tags_enumerated_absolute" : self.validate_bool,
                "hide_empty_tags" : self.validate_bool,
                "search_attributes" : self.validate_string_list,
                "cursor" : self.validate_taglist_cursor,
                "border" : self.validate_bool,
            },

            "story" :
            {
                "enumerated" : self.validate_bool,
                "format" : self.validate_string,
                "format_attrs" : self.validate_string_list,

                "selected": self.validate_string,
                "unselected":  self.validate_string,
                "selected_end": self.validate_string ,
                "unselected_end": self.validate_string,
                "read": self.validate_string,
                "unread": self.validate_string,
                "read_end": self.validate_string,
                "unread_end": self.validate_string,
                "marked": self.validate_string,
                "unmarked": self.validate_string,
                "marked_end": self.validate_string,
                "unmarked_end": self.validate_string,
            },

            "input" : { "window" : self.validate_window },

            "errorbox" :
            {
                "window" : self.validate_window,
                "key" : self.validate_key,
            },

            "infobox" :
            {
                "window" : self.validate_window,
                "key" : self.validate_key,
            },

            "main" : { "key" : self.validate_key },

            "screen" : { "key" : self.validate_key },

            "color" :
            {
                "defbg" : self.validate_color,
                "deffg" : self.validate_color,
                # See also setup for numeric settings below
            },

            "kill_daemon_on_exit" : self.validate_bool
        }

        for i in range(0, 256):
            self.validators["color"][str(i)] = self.validate_color

        self.config = {
            "browser" :
            {
                "path" : "firefox %u",
                "text" : False
            },

            "tags" : r"maintag:.*",
            "tagorder" : [],

            "tag" :
            {
                "format" : DEFAULT_TAG_FSTRING,
                "selected" : "%R",
                "unselected" : "",
                "selected_end" : "%r",
                "unselected_end" : "",
            },

            "update" :
            {
                "style" : "append",
                "auto" :
                {
                    "interval" : 20,
                    "enabled" : True
                }
            },

            "reader" :
            {
                "window" :
                {
                    "maxwidth" : 0,
                    "maxheight" : 0,
                    "float" : True,
                    "align" : "topleft",
                    "border" : "smart",
                },

                "enumerate_links" : False,
                "show_description" : True,
                "show_enclosures" : True,
                "key" :
                {
                    "space" : "destroy",
                    "d" : "toggle reader.show_description",
                    "l" : "toggle reader.enumerate_links",
                    "g" : "goto",
                    "f" : "fetch",
                    "down" : "scroll-down",
                    "up" : "scroll-up",
                    "j" : "scroll-down",
                    "k" : "scroll-up",
                    "npage" : "page-down",
                    "ppage" : "page-up",
                    'n' : 'destroy & rel-set-cursor 1 & item-state read & reader',
                    'p' : 'destroy & rel-set-cursor -1 & item-state read & reader',
                },
            },

            "taglist" :
            {
                "window" :
                {
                    "maxwidth" : 0,
                    "maxheight" : 0,
                    "float" : False,
                    "align" : "neutral",
                    "border" : "none",
                },

                "tags_enumerated" : False,
                "tags_enumerated_absolute" : False,
                "hide_empty_tags" : True,
                "border" : False,
                "search_attributes" : [ "title" ],

                "key" :
                {
                    "space" : "foritem & item-state read & reader",
                    "g" : "foritems & goto & item-state read & clearitems",
                    "E" : "toggle taglist.tags_enumerated",
                    "e" : "toggle story.enumerated",
                    "R" : "item-state read *",
                    "U" : "item-state -read *",
                    "r" : "tag-state read",
                    "u" : "tag-state -read",
                    "npage" : "page-down",
                    "ppage" : "page-up",
                    "down" : "rel-set-cursor 1",
                    "j" : "rel-set-cursor 1",
                    "up" : "rel-set-cursor -1",
                    "k" : "rel-set-cursor -1",
                    "C-u" : "unset-cursor",
                    "+" : "promote",
                    "-" : "demote",
                    "J" : "next-tag",
                    "K" : "prev-tag",
                    "c" : "toggle-collapse",
                    "C" : "collapse *",
                    "V" : "uncollapse *",
                    "$" : "item-state read tag,0-.",
                    "/" : "search",
                    "?" : "search-regex",
                    "n" : "next-marked",
                    "p" : "prev-marked",
                    "M" : "item-state -marked *",
                },

                "cursor" :
                {
                    "type" : "edge",
                    "scroll" : "scroll",
                    "edge" : 5,
                },
            },

            "story" :
            {
                "enumerated" : False,
                "format" : DEFAULT_FSTRING,
                "format_attrs" : [ "title" ],

                # Themability
                "selected": "%R",
                "unselected": "",
                "selected_end": "%r",
                "unselected_end": "",
                "read": "%3",
                "unread": "%2%B",
                "read_end": "%0",
                "unread_end": "%b%0",
                "marked": "*%8%B",
                "unmarked": "",
                "marked_end": "%b%0",
                "unmarked_end": "",
            },

            "input" :
            {
                "window" :
                {
                    "maxwidth" : 0,
                    "maxheight" : 0,
                    "float" : False,
                    "align" : "bottom",
                    "border" : "none",
                }
            },

            "errorbox" :
            {
                "window" :
                {
                    "maxwidth" : 0,
                    "maxheight" : 0,
                    "float" : True,
                    "align" : "topleft",
                    "border" : "full",
                },

                "key" :
                {
                    "down" : "scroll-down",
                    "up" : "scroll-up",
                    "npage" : "page-down",
                    "ppage" : "page-up",
                    "space" : "destroy",
                }
            },

            "infobox" :
            {
                "window" :
                {
                    "maxwidth" : 0,
                    "maxheight" : 0,
                    "float" : True,
                    "align" : "topleft",
                    "border" : "full",
                },

                "key" :
                {
                    "down" : "scroll-down",
                    "up" : "scroll-up",
                    "npage" : "page-down",
                    "ppage" : "page-up",
                    "space" : "destroy",
                }
            },

            "main" :
            {
                "key" :
                {
                    ":" : "command",
                    "q" : "quit",
                    "\\" : "refresh",
                }
            },

            "screen" :
            {
                "key" :
                {
                    "tab" : "focus-rel 1",
                }
            },

            "color" :
            {
                "defbg" : -1,
                "deffg" : -1,
                "0" : curses.COLOR_WHITE,
                "1" : curses.COLOR_BLUE,
                "2" : curses.COLOR_YELLOW,
                "3" : curses.COLOR_BLUE,
                "4" : curses.COLOR_GREEN,
                "5" : curses.COLOR_MAGENTA,
                "6" :
                {
                    "fg" : curses.COLOR_WHITE,
                    "bg" : curses.COLOR_RED,
                },
                "7" : curses.COLOR_WHITE,
            },

            "kill_daemon_on_exit" : False
        }

        for i in range(8, 256):
            self.config["color"][str(i)] = i

        self.tag_validators = {
            "enumerated" : self.validate_bool,
            "collapsed" : self.validate_bool,
            "extra_tags" : self.validate_string_list,
        }

        self.tag_config = {}

        self.tag_template_config = {
            "enumerated" : False,
            "collapsed" : False,
            "extra_tags" : [],
        }

        self.aliases = {
                "browser" : "remote one-config CantoCurses.browser.path",
                "txt_browser" : "remote one-config --eval CantoCurses.browser.text",
                "add" : "remote addfeed",
                "del" : "remote delfeed",
                "list" : "remote listfeeds",
                "q" : "quit",
                "filter" : "transform",
                "sort" : "transform",
                "cursor_type" : "remote one-config CantoCurses.taglist.cursor.type",
                "cursor_scroll" : "remote one-config CantoCurses.taglist.cursor.scroll",
                "cursor_edge" : "remote one-config --eval CantoCurses.taglist.cursor.edge",
                "story_unselected" : "remote one-config CantoCurses.story.unselected",
                "story_selected" : "remote one-config CantoCurses.story.selected",
                "story_selected_end" : "remote one-config CantoCurses.story.selected_end",
                "story_unselected_end" : "remote one-config CantoCurses.story.unselected_end",
                "story_unread" : "remote one-config CantoCurses.story.unread",
                "story_read" : "remote one-config CantoCurses.story.read",
                "story_read_end" : "remote one-config CantoCurses.story.read_end",
                "story_unread_end" : "remote one-config CantoCurses.story.unread_end",
                "story_unmarked" : "remote one-config CantoCurses.story.unmarked",
                "story_marked" : "remote one-config CantoCurses.story.marked",
                "story_marked_end" : "remote one-config CantoCurses.story.marked_end",
                "story_unmarked_end" : "remote one-config CantoCurses.story.unmarked_end",
                "tag_unselected" : "remote one-config CantoCurses.tag.unselected",
                "tag_selected" : "remote one-config CantoCurses.tag.selected",
                "tag_selected_end" : "remote one-config CantoCurses.tag.selected_end",
                "tag_unselected_end" : "remote one-config CantoCurses.tag.unselected_end",
                "update_interval" : "remote one-config --eval CantoCurses.update.auto.interval",
                "update_style" : "remote one-config CantoCurses.update.style",
                "update_auto" : "remote one-config --eval CantoCurses.update.auto.enabled",
                "border" : "remote one-config --eval CantoCurses.taglist.border",
                "reader_align" : "remote one-config CantoCurses.reader.window.align",
                "reader_float" : "remote one-config --eval CantoCurses.reader.window.float",
                "keep_time" : "remote one-config --eval defaults.keep_time",
                "keep_unread" : "remote one-config --eval defaults.keep_unread",
                "kill_daemon_on_exit" : "remote one-config --eval CantoCurses.kill_daemon_on_exit"
        }

        self.start_pthread()

        self.write("WATCHNEWTAGS", [])
        self.write("WATCHDELTAGS", [])
        self.write("LISTTAGS", "")
        self.write("WATCHCONFIGS", "")
        self.write("CONFIGS", [])

        # Spin, may want to convert this into an event, but for now it
        # takes virtually no time and makes it so that we don't have to 
        # check if we're init'd before using *_opt functions.

        while(not self.initd):
            pass

    def validate_uint(self, val, d):
        if type(val) == int and val >= 0:
            return (True, val)
        return (False, False)

    def validate_string(self, val, d):
        if type(val) == str:
            return (True, val)
        return (False, False)

    def validate_bool(self, val, d):
        if val in [ True, False ]:
            return (True, val)
        return (False, False)

    def validate_update_style(self, val, d):
        if val in [ "maintain", "append" ]:
            return (True, val)
        return (False, False)

    def validate_tags(self, val, d):
        try:
            re.compile(val)
        except:
            return (False, False)
        return (True, val)

    def validate_tag_order(self, val, d):
        if type(val) != list:
            return (False, False)

        # Strip items no longer relevant
        for item in val[:]:
            if item not in self.vars["strtags"]:
                val.remove(item)

        # Ensure all tags are inluded
        for tag in self.vars["strtags"]:
            if tag not in val:
                val.append(tag)

        return (True, val)

    def validate_window(self, val, d):
        # Ensure all settings exist
        for setting in [ "border", "maxwidth", "maxheight", "align", "float" ]:
            if setting not in val:
                log.debug("Couldn't find %s setting" % setting)
                val[setting] = d[setting]

        # Ensure all settings are in their correct range
        if val["border"] not in ["full", "none", "smart"]:
            log.error("border setting must = full OR none OR smart")
            return (False, False)

        if val["float"] not in [ True, False ]:
            log.error("float must be True or False")
            return (False, False)

        for int_setting in ["maxwidth", "maxheight" ]:
            if type(val[int_setting]) != int or val[int_setting] < 0:
                log.error("%s must be a positive integer" % int_setting)
                return (False, False)

        float_aligns = [ "topleft", "topright", "center", "neutral",\
                "bottomleft", "bottomright" ]

        tile_aligns = [ "top", "left", "bottom", "right", "neutral" ]

        if val["float"]:
            if val["align"] not in float_aligns:
                log.error("%s is not a valid alignment for a floating window" % val["align"])
                return (False, False)
        else:
            if val["align"] not in tile_aligns:
                log.error("%s is not a valid alignment for a tiled window" % val["align"])
                return (False, False)

        return (True, val)

    # This doesn't validate that the command will actually work, just that the
    # pair is of the correct types.

    def validate_key(self, val, d):
        if type(val) != dict:
            return (False, False)

        for key in list(val.keys()):
            if type(key) != str:
                return (False, False)

            if type(val[key]) != str:
                return (False, False)

        # For keys, because we don't want to specify each and every possible
        # key explicitly, so we merge in default keys. If a user wants to
        # ignore a default key, he can set it to None and it won't be merged
        # over.

        for key in list(d.keys()):
            if key not in val:
                val[key] = d[key]

        return (True, val)

    def validate_color(self, val, d, dict_ok=True):
        # Integer, and in the valid color range
        if type(val) == int and val >= -1 and val <= 255:
            return (True, val)

        if type(val) == dict and dict_ok:
            fg_g, bg_g = (False, False)
            r = {}

            # Not specified correctly...
            if "fg" in val:
                fg_g, fg_v = self.validate_color(val["fg"], {}, False)
                if fg_g:
                    r["fg"] = fg_v
            if "bg" in val:
                bg_g, bg_v = self.validate_color(val["bg"], {}, False)
                if bg_g:
                    r["bg"] = bg_v

            if not r:
                return (False, False)
            return (True, r)

        # We have no idea what to do with this crap...
        if type(val) != str:
            return (False, False)

        # See if it's an integer as a string
        try:
            ival = int(val)
            return (True, ival)
        except:
            return color_translate(val)

        return (False, False)

    def validate_string_list(self, val, d):
        if type(val) != list:
            return (False, False)

        r = []
        for item in val:
            if type(item) == str:
                r.append(item)
            else:
                return (False, False)

        return (True, r)

    def validate_taglist_cursor(self, val, d):
        if type(val) != dict:
            return (False, False)

        for setting in [ "type","scroll","edge" ]:
            if setting not in val:
                val[setting] = d[setting]

        if val["type"] not in ["edge","top","middle","bottom"]:
            log.error("Cursor type %s unknown!" % (val["type"],))
            return (False, False)

        if val["scroll"] not in ["scroll", "page"]:
            log.error("Cursor scroll type %s unknown!" % (val["scroll"],))

        if type(val["edge"]) != int or val["edge"] < 0:
            log.error("Cursor edge invalid, must be int >= 0: %s" % (val["edge"],))
            return (False, False)

        return (True, val)

    def _list_diff(self, cur, old):
        adds = []
        dels = []

        for item in old:
            if item not in cur:
                dels.append(item)

        for item in cur:
            if item not in old:
                adds.append(item)

        return (adds, dels)

    # Recursively validate config c, with validators in v, falling back on d
    # when it failed. Return a dict containing all of the changes actually
    # made.

    # Note that unknown values are detected only to avoid access errors, they
    # are totally ignored and will never get changes processed.

    def validate_config(self, c, d, v):
        changes = {}
        deletions = {}

        # Sub in non-existent values:

        for key in list(v.keys()):
            if key not in c:
                c[key] = d[key]

        # Validate existing values.

        for key in list(c.keys()):
            log.debug("validating %s" % key)
            # Unknown values, don't validate
            if key not in v:
                continue

            # Key is section, recurse, only add changes if there
            # are actual changes.

            elif type(v[key]) == dict:
                chgs, dels =  self.validate_config(c[key], d[key], v[key])
                if chgs:
                    changes[key] = chgs
                if dels:
                    deletions[key] = dels

            # Key is basic, validate
            else:
                good, val = v[key](c[key], d[key])

                # Value is good, pass on
                if good:
                    if val != d[key]:
                        if type(val) == list:
                            chgs, dels, = self._list_diff(val, d[key])
                            if dels:
                                deletions[key] = dels
                        changes[key] = val
                    c[key] = val

                # Value is bad, revert
                else:
                    err = "config %s was bad (%s) reverting to default (%s)" %\
                            (key, c[key], d[key])

                    #if not self.glog_handler:
                    #    self.early_errors.append(err)
                    #    log.error("Will display " + err)
                    #else:
                    log.error(err)

                    changes[key] = d[key]
                    c[key] = d[key]

        return changes, deletions

    # We use strtags to validate tag order, and also to populate the
    # TagUpdater()

    @write_lock(config_lock)
    def prot_listtags(self, tags):
        log.debug("listtags: %s" % tags)
        self.vars["strtags"] = tags

    # configs accepts any changes, calls the opt_change hooks and if write is
    # set, sends those changes to the daemon. It's called both when receving
    # CONFIGS from the daemon and when we change opts internally (thus the
    # write flag).

    # Note that changes are the only ones propagated through hooks because they
    # are a superset of deletions (i.e. a deletion counts as a change).

    def _prot_configs(self, given, write = False):
        log.debug("prot_configs given: %s" % given)

        if "tags" in given:
            for tag in list(given["tags"].keys()):
                ntc = given["tags"][tag]

                tc = self._get_tag_conf(tag)

                changes, deletions =\
                        self.validate_config(ntc, tc, self.tag_validators)

                if changes:
                    self.tag_config[tag] = ntc
                    call_hook("curses_tag_opt_change", [ { tag : changes } ])

                    if write:
                        self.write("SETCONFIGS", { "tags" : { tag : changes }})

                if deletions and write:
                    self.write("DELCONFIGS", { "tags" : { tag : deletions }})

        if "CantoCurses" in given:
            new_config = given["CantoCurses"]

            changes, deletions =\
                    self.validate_config(new_config, self.config,\
                    self.validators)

            if changes:
                self.config = new_config
                call_hook("curses_opt_change", [ changes ])

                if write:
                    self.write("SETCONFIGS", { "CantoCurses" : changes })

            if deletions and write:
                self.write("DELCONFIGS", { "CantoCurses" : deletions })

        self.initd = True

    @write_lock(config_lock)
    def prot_configs(self, given, write = False):
        return self._prot_configs(given, write)

    # Process new tags.

    @write_lock(config_lock)
    def prot_newtags(self, tags):
        c = self._get_conf()

        for tag in tags:
            if tag not in self.vars["strtags"]:
                log.info("New tag %s" % tag)

                # If we don't have configuration for this
                # tag already, substitute the default template.

                if tag not in self.tag_config:
                    log.debug("Using default tag config for %s" % tag)
                    self.tag_config[tag] = self.tag_template_config.copy()

                call_hook("curses_new_tag", [ tag ])

            if tag not in c["tagorder"]:
                c["tagorder"] = self.config["tagorder"] + [ tag ]

        self._set_conf(c)
        self._eval_tags()

    @write_lock(config_lock)
    def prot_deltags(self, tags):
        c = self._get_conf()

        for tag in tags:
            if tag in self.vars["strtags"]:
                new_alltags = self.vars["alltags"]

                # Allow Tag obj to cleanup hooks.
                tagobj = new_alltags[self.vars["strtags"].index(tag)]
                tagobj.die()

                # Remove it from alltags.
                del new_alltags[self.vars["strtags"].index(tag)]
                call_hook("curses_del_tag", tag)
            else:
                log.warn("Got DELTAG for non-existent tag!")

            if tag in c["tagorder"]:
                c["tagorder"] = [ x for x in self.config["tagorder"] if x != tag ]

        self._set_conf(c)
        self._eval_tags()

    def _eval_tags(self):
        prevtags = self.vars["curtags"]

        sorted_tags = []
        r = re.compile(self.config["tags"])
        for tag in self.vars["alltags"]:
            if r.match(tag.tag):
                sorted_tags.append((self.config["tagorder"].index(tag.tag), tag))
        sorted_tags.sort()

        self.set_var("curtags", [ x for (i, x) in sorted_tags ])

        if not self.vars["curtags"]:
            log.warn("NOTE: Current 'tags' setting eliminated all tags!")

        # If evaluated tags differ, we need to let other know.

        if prevtags != self.vars["curtags"]:
            log.debug("Evaluated Tags Changed: %s" % [ t.tag for t in self.vars["curtags"]])
            call_hook("curses_eval_tags_changed", [])

    @write_lock(config_lock)
    def eval_tags(self):
        return self._eval_tags()

    # This needs to hold var lock, but we also want to avoid calling the var
    # hooks while holding locks, so we do it manually. Vars are a bit different
    # from opts because a set var can result in another set var, where that
    # should never be the case for opts.

    def set_var(self, tweak, value):
        # We only care if the value is different, or it's a message
        # value, which should always cause a fresh message display,
        # even if it's the same error as before.

        var_lock.acquire_read()
        if self.vars[tweak] != value:
            var_lock.release_read()
            var_lock.acquire_write()

            # If we're selecting or unselecting a story, then
            # we need to make sure it doesn't disappear.

            if tweak in [ "selected", "reader_item" ]:
                if self.vars[tweak] and hasattr(self.vars[tweak], "id"):
                    self.vars["protected_ids"].remove(self.vars[tweak].id)
                    self.write("UNPROTECT",\
                            { "filter-immune" : [ self.vars[tweak].id ] })

                    # Fake a TAGCHANGE because unprotected items have the
                    # possibility to filtered out and we only refresh items for
                    # tags that get a TAGCHANGE on tick.

                    for tag in self.vars["alltags"]:
                        if self.vars[tweak].id in tag.get_ids():
                            call_hook("curses_tagchange", [ tag.tag ] )
                            #self.prot_tagchange(tag.tag)

                if value and hasattr(value, "id"):
                    # protected_ids just tells the prot_items to not allow
                    # this item to have it's auto protection stripped.

                    self.vars["protected_ids"].append(value.id)

                    # Set an additional protection, filter-immune so hardened
                    # filters won't eliminate it.

                    self.write("PROTECT", { "filter-immune" : [ value.id ] })

            self.vars[tweak] = value
            var_lock.release_write()

            call_hook("curses_var_change", [{ tweak : value }])
        else:
            var_lock.release_read()

    @read_lock(var_lock)
    def get_var(self, tweak):
        if tweak in self.vars:
            return self.vars[tweak]
        raise Exception("Unknown variable: %s" % (tweak,))

    # Overall configuration operation functions. The paradigm is that internal
    # code can "get" the conf, which is a copy of the real conf, modify it,
    # then "set" the conf which will properly process the changes.

    def _set_conf(self, conf):
        self._prot_configs({"CantoCurses" : conf }, True)

    # prot_configs handles locking

    def set_conf(self, conf):
        self.prot_configs({"CantoCurses" : conf }, True)

    def set_tag_conf(self, tag, conf):
        self.prot_configs({ "tags" : { tag : conf } }, True)

    def _get_conf(self):
        return eval(repr(self.config), {}, {})

    @read_lock(config_lock)
    def get_conf(self):
        return self._get_conf()

    def _get_tag_conf(self, tag):
        if tag in self.tag_config:
            return eval(repr(self.tag_config[tag]), {}, {})
        return eval(repr(self.tag_template_config))

    @read_lock(config_lock)
    def get_tag_conf(self, tag):
        return self._get_tag_conf(tag)

    def _get_opt(self, option, d):
        valid, value = access_dict(d, option)
        if not valid:
            return None
        return value

    def _set_opt(self, option, value, d):
        assign_to_dict(d, option, value)

    @write_lock(config_lock)
    def set_opt(self, option, value):
        c = self.get_conf()
        self._set_opt(option, value, c)
        self.set_conf(c)

    @read_lock(config_lock)
    def get_opt(self, option):
        c = self.get_conf()
        return  self._get_opt(option, c)

    @write_lock(config_lock)
    def set_tag_opt(self, tag, option, value):
        tc = self.get_tag_conf(tag)
        self._set_opt(option, value, tc)
        self.set_tag_conf(tag, tc)

    @read_lock(config_lock)
    def get_tag_opt(self, tag, option):
        tc = self.get_tag_conf(tag)
        return self._get_opt(option, tc)


config = CantoCursesConfig()
