# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
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

DEFAULT_FSTRING = "%1%?{sel}(%{selected}:%{unselected})%?{rd}(%{read}:%{unread})%?{m}(%{marked}:%{unmarked})%{pre}%t%{post}%?{m}(%{marked_end}:%{unmarked_end})%?{rd}(%{read_end}:%{unread_end})%?{sel}(%{selected_end}:%{unselected_end})%0"

DEFAULT_TAG_FSTRING = "%1%?{sel}(%{selected}:%{unselected})%?{c}([+]:[-])%{pre} %t %{post} [%B%2%n%1%b]%?{sel}(%{selected_end}:%{unselected_end})%0"

from .locks import config_lock
from .subthread import SubThread

from threading import Thread
import traceback
import logging
import curses   # Colors
import re

log = logging.getLogger("CONFIG")

# eval settings need to be somehow converted when read from input.

# These are regexes so that window and color types can be handled with easy
# wildcards, but care has to be taken.

eval_settings = [\
    "defaults\\.rate", "feed\\.rate",
    "defaults\\.keep_time", "feed\\.keep_time",
    "defaults\\.keep_unread", "feed\\.keep_unread",
    "update\\.auto.enabled", "update\\.auto\\.interval",
    "browser\\.text", "taglist\\.border",
    "kill_daemon_on_exit",
    ".*\\.window\\.(maxwidth|maxheight|float)",
    "color\\..*", "tag.(enumerated|collapsed|extra_tags)",
    "reader.(enumerate_links|show_description|show_enclosures)",
    "taglist.(border|tags_enumerated|tags_enumerated_absolute|hide_empty_tags|search_attributes)",
    "taglist.cursor.edge",
    "story.(format_attrs|enumerated)"
]

# Do the one-time compile for the setting regexes. This is called after
# plugins are evaluated, but before curses_start

def finalize_eval_settings():
    global eval_settings
    eval_settings = [ re.compile(x) for x in eval_settings ]

def needs_eval(option):
    for reobj in eval_settings:
        if reobj.match(option):
            return True
    return False

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
            "dispel_msg" : False,
            "input_prompt" : "",
            "input_do_completions" : True,
            "input_completion_root" : None,
            "input_completions" : [],
            "reader_item" : None,
            "reader_offset" : 0,
            "errorbox_offset" : 0,
            "infobox_offset" : 0,
            "selected" : None,
            "target_obj" : None,
            "target_offset" : 0,
            "strtags" : [],
            "curtags" : [],
            "alltags" : [],
            "needs_refresh" : False,
            "needs_redraw" : False,
            "needs_resize" : False,
            "transforms" : [],
            "taglist_visible_tags" : [],
        }

        self.validators = {
            "browser" :
            {
                "path" : self.validate_string,
                "text" : self.validate_bool,
            },

            "tags" : self.validate_tags,
            "tagorder" : self.validate_tag_order,

            "tagobj" :
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
                "path" : "firefox",
                "text" : False
            },

            "tags" : r"maintag:.*",
            "tagorder" : [],

            "tagobj" :
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
                    "s" : "show-summary",
                    "l" : "show-links",
                    "e" : "show-enclosures",
                    "g" : "goto",
                    "f" : "fetch",
                    "down" : "scroll-down",
                    "up" : "scroll-up",
                    "j" : "scroll-down",
                    "k" : "scroll-up",
                    "npage" : "page-down",
                    "ppage" : "page-up",
                    'n' : 'destroy & next-item & item-state read & reader',
                    'p' : 'destroy & prev-item & item-state read & reader',
                    'N' : 'destroy & next-tag & item-state read & reader',
                    'P' : 'destroy & prev-tag & item-state read & reader',
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
                    "down" : "next-item",
                    "j" : "next-item",
                    "up" : "prev-item",
                    "k" : "prev-item",
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
                    "n" : "next-marked",
                    "p" : "prev-marked",
                    "M" : "item-state -marked *",
                    "m" : "item-state %marked",
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
                    "?" : "help",
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
            "transform" : self.validate_string,
        }

        self.tag_config = {}

        self.tag_template_config = {
            "enumerated" : False,
            "collapsed" : False,
            "extra_tags" : [],
            "transform" : "None"
        }

        self.daemon_defaults = {}
        self.daemon_feedconf = []

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
        self.config["tagorder"] = tags

    # configs accepts any changes, calls the opt_change hooks and if write is
    # set, sends those changes to the daemon. It's called both when receving
    # CONFIGS from the daemon and when we change opts internally (thus the
    # write flag).

    # Note that changes are the only ones propagated through hooks because they
    # are a superset of deletions (i.e. a deletion counts as a change).

    @write_lock(config_lock)
    def prot_configs(self, given, write = False):
        log.debug("prot_configs given: %s" % given)

        if "tags" in given:
            for tag in list(given["tags"].keys()):
                ntc = given["tags"][tag]

                tc = self.get_tag_conf(tag)

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

        if "defaults" in given:

            # We don't honor any default settings, so just record them
            # and pass them on to the daemon if write

            self.daemon_defaults.update(given["defaults"])
            if write:
                self.write("SETCONFIGS", { "defaults" : self.daemon_defaults })

        if "feeds" in given:

            self.daemon_feedconf = given["feeds"]
            if write:
                self.write("SETCONFIGS", { "feeds" : self.daemon_feedconf })

        self.initd = True

    # Process new tags.

    @write_lock(config_lock)
    def prot_newtags(self, tags):

        if not self.initd:
            for tag in tags:
                self.vars["strtags"].append(tag)
                self.config["tagorder"].append(tag)
            return

        c = self.get_conf()

        # Likely the same as tags
        newtags = []

        for tag in tags:
            if tag not in c["tagorder"]:
                c["tagorder"] = self.config["tagorder"] + [ tag ]

            if tag not in self.vars["strtags"]:

                # If we don't have configuration for this
                # tag already, substitute the default template.

                if tag not in self.tag_config:
                    log.debug("Using default tag config for %s" % tag)
                    self.tag_config[tag] = self.tag_template_config.copy()

                self.vars["strtags"].append(tag)
                newtags.append(tag)

        self.set_conf(c)

        for tag in newtags:
            log.debug("New tag %s" % tag)
            call_hook("curses_new_tag", [ tag ])

        self.eval_tags()


    @write_lock(config_lock)
    def prot_deltags(self, tags):

        if not self.initd:
            for tag in tags:
                if tag in self.vars["strtags"]:
                    self.vars["strtags"].remove(tag)
                if tag in self.config["tagorder"]:
                    self.config["tagorder"].append(tag)
            return

        c = self.get_conf()

        for tag in tags:
            if tag in self.vars["strtags"]:
                new_alltags = self.vars["alltags"]

                i, tagobj = [ x for x in enumerate(new_alltags) if x[1].tag == tag ][0]
                tagobj.die()

                # Remove it from our vars.
                del new_alltags[i]
                self.vars["alltags"] = new_alltags
                self.vars["strtags"].remove(tag)

                call_hook("curses_del_tag", tag)
            else:
                log.debug("Got DELTAG for non-existent tag!")

            if tag in c["tagorder"]:
                c["tagorder"] = [ x for x in self.config["tagorder"] if x != tag ]

        self.set_conf(c)
        self.eval_tags()

    @write_lock(config_lock)
    def eval_tags(self):
        prevtags = self.vars["curtags"]

        sorted_tags = []
        r = re.compile(self.config["tags"])
        for tag in self.vars["alltags"]:

            # This can happen between the time that a tag is removed from the config
            # and the time that we receive a DELTAG event.
            if tag.tag not in self.config["tagorder"]:
                continue

            elif r.match(tag.tag):
                sorted_tags.append((self.config["tagorder"].index(tag.tag), tag))
        sorted_tags.sort()

        self.set_var("curtags", [ x for (i, x) in sorted_tags ])

        if not self.vars["curtags"]:
            log.warn("NOTE: Current 'tags' setting eliminated all tags!")

        # If evaluated tags differ, we need to let other know.

        if prevtags != self.vars["curtags"]:
            log.debug("Evaluated Tags Changed: %s" % [ t.tag for t in self.vars["curtags"]])
            call_hook("curses_eval_tags_changed", [])

    # This needs to hold var lock, but we also want to avoid calling the var
    # hooks while holding locks, so we do it manually. Vars are a bit different
    # from opts because a set var can result in another set var, where that
    # should never be the case for opts.

    def set_var(self, tweak, value):
        # We only care if the value is different, or it's a message
        # value, which should always cause a fresh message display,
        # even if it's the same error as before.

        config_lock.acquire_write()
        if self.vars[tweak] != value:

            # If we're selecting or unselecting a story, then
            # we need to make sure it doesn't disappear.

            self.vars[tweak] = value
            config_lock.release_write()

            call_hook("curses_var_change", [{ tweak : value }])
        else:
            config_lock.release_write()

    @read_lock(config_lock)
    def get_var(self, tweak):
        if tweak in self.vars:
            return self.vars[tweak]
        raise Exception("Unknown variable: %s" % (tweak,))

    # Overall configuration operation functions. The paradigm is that internal
    # code can "get" the conf, which is a copy of the real conf, modify it,
    # then "set" the conf which will properly process the changes.

    # prot_configs handles locking

    def set_conf(self, conf):
        self.prot_configs({"CantoCurses" : conf }, True)

    def set_tag_conf(self, tag, conf):
        self.prot_configs({ "tags" : { tag : conf } }, True)

    def set_def_conf(self, conf):
        self.prot_configs({ "defaults" : conf }, True)

    def set_feed_conf(self, name, conf):
        config_lock.acquire_read()
        d_f = eval(repr(self.daemon_feedconf), {}, {})
        config_lock.release_read()

        for f in d_f:
            if f["name"] == name:
                log.debug("updating %s with %s" % (f, conf))
                f.update(conf)
                break
        else:
            d_f.append(conf)

        self.prot_configs({ "feeds" : d_f }, True)

    @read_lock(config_lock)
    def get_conf(self):
        return eval(repr(self.config), {}, {})

    @read_lock(config_lock)
    def get_tag_conf(self, tag):
        if tag in self.tag_config:
            return eval(repr(self.tag_config[tag]), {}, {})
        return eval(repr(self.tag_template_config), {}, {})

    @read_lock(config_lock)
    def get_def_conf(self):
        return eval(repr(self.daemon_defaults), {}, {})

    @read_lock(config_lock)
    def get_feed_conf(self, name):
        for f in self.daemon_feedconf:
            if f["name"] == name:
                return eval(repr(f), {}, {})
        return None

    @write_lock(config_lock)
    def set_opt(self, option, value):
        c = self.get_conf()
        assign_to_dict(c, option, value)
        self.set_conf(c)

    @read_lock(config_lock)
    def get_opt(self, option):
        c = self.get_conf()
        valid, value = access_dict(c, option)
        if not valid:
            return None
        return value

    @write_lock(config_lock)
    def set_tag_opt(self, tag, option, value):
        tc = self.get_tag_conf(tag)
        assign_to_dict(tc, option, value)
        self.set_tag_conf(tag, tc)

    @read_lock(config_lock)
    def get_tag_opt(self, tag, option):
        tc = self.get_tag_conf(tag)
        valid, value = access_dict(tc, option)
        if not valid:
            return None
        return value

    @write_lock(config_lock)
    def switch_tags(self, tag1, tag2):
        c = self.get_conf()

        t1_idx = c["tagorder"].index(tag1.tag)
        t2_idx = c["tagorder"].index(tag2.tag)

        c["tagorder"][t1_idx] = tag2.tag
        c["tagorder"][t2_idx] = tag1.tag

        self.set_conf(c)

        self.eval_tags()

config = CantoCursesConfig()
