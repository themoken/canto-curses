# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

COMPATIBLE_VERSION = 0.4

from canto_next.hooks import call_hook
from canto_next.plugins import Plugin
from canto_next.remote import assign_to_dict, access_dict
from canto_next.format import escsplit

from .command import CommandHandler, command_format
from .story import DEFAULT_FSTRING
from .text import ErrorBox, InfoBox
from .screen import Screen, color_translate
from .tag import Tag, DEFAULT_TAG_FSTRING

from queue import Queue, Empty
import logging
import curses
import pprint
import sys
import re

log = logging.getLogger("GUI")
pp = pprint.PrettyPrinter(indent=4)

class GraphicalLog(logging.Handler):
    def __init__(self, callbacks, screen):
        logging.Handler.__init__(self)
        self.callbacks = callbacks
        self.screen = screen

    def _emit(self, var, window_type, record):
        if window_type not in self.screen.window_types:
            self.callbacks["set_var"](var, record.message)
            self.screen.add_window_callback(window_type)
        else:
            cur = self.callbacks["get_var"](var)
            cur += "\n" + record.message
            self.callbacks["set_var"](var, cur)
        self.callbacks["set_var"]("needs_refresh", True)

    def emit(self, record):
        if record.levelno == logging.INFO:
            self._emit("info_msg", InfoBox, record)
        elif record.levelno == logging.ERROR:
            self._emit("error_msg", ErrorBox, record)

class GuiPlugin(Plugin):
    pass

CONN_NEED_NOTIFY = 1
CONN_NOTIFIED = 2

class CantoCursesGui(CommandHandler):
    def __init__(self, backend):
        CommandHandler.__init__(self)

        self.plugin_class = GuiPlugin
        self.update_plugin_lookups()

        self.input_queue = Queue()

        self.backend = backend
        self.screen = None

        self.update_interval = 0

        #Lines to be emitted after a graphical log is setup.
        self.early_errors = []
        self.glog_handler = None

        # Buffers for items being received.
        self.item_tag = None
        self.item_buf = []
        self.item_removes = []
        self.item_adds = []

        self.disconnect_message =\
""" Disconnected!

Please use :reconnect if the daemon is still running.

Until reconnected, it will be impossible to fetch any information, and any state changes will be lost."""

        self.reconnect_message =\
""" Successfully Reconnected!"""

        # Asynchronous notification flags
        self.disconn = 0
        self.reconn = 0
        self.ticked = False
        self.winched = False

        # Variables that affect the overall operation.

        self.vars = {
            "location" : self.backend.location_args,
            "error_msg" : "No error.",
            "info_msg" : "No info.",
            "reader_item" : None,
            "reader_offset" : 0,
            "errorbox_offset" : 0,
            "infobox_offset" : 0,
            "selected" : None,
            "old_selected" : None,
            "old_toffset" : 0,
            "target_obj" : None,
            "target_offset" : 0,
            "curtags" : [],
            "alltags" : [],
            "needs_refresh" : False,
            "needs_redraw" : False,
            "needs_resize" : False,
            "protected_ids" : [],
            "transforms" : [],
            "taglist_visible_tags" : [],
        }

        self.callbacks = {
            "set_var" : self.set_var,
            "get_var" : self.get_var,
            "set_conf" : self.set_conf,
            "get_conf" : self.get_conf,
            "set_tag_conf" : self.set_tag_conf,
            "get_tag_conf" : self.get_tag_conf,
            "get_opt" : self.get_opt,
            "set_opt" : self.set_opt,
            "get_tag_opt" : self.get_tag_opt,
            "set_tag_opt" : self.set_tag_opt,
            "switch_tags" : self.switch_tags,
            "write" : self.write,
            "prio_write" : self.prio_write,
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
                "0" : self.validate_color,
                "1" : self.validate_color,
                "2" : self.validate_color,
                "3" : self.validate_color,
                "4" : self.validate_color,
                "5" : self.validate_color,
                "6" : self.validate_color,
                "7" : self.validate_color,
            },

            "kill_daemon_on_exit" : self.validate_bool
        }

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
                    "$" : "item-state read t:. 0-.",
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

        self.daemon_init()

    def daemon_init(self):

        # Make sure that we're not mismatching versions.

        self.write("VERSION", "")
        r = self.wait_response("VERSION")
        if r[1] != COMPATIBLE_VERSION:
            s = "Incompatible daemon version (%s) detected! Expected: %s" %\
                (r[1], COMPATIBLE_VERSION)
            log.debug(s)
            print(s)
            sys.exit(-1)
        else:
            log.debug("Got compatible daemon version.")

        # Start watching for new and deleted tags.
        self.write("WATCHNEWTAGS", [])
        self.write("WATCHDELTAGS", [])

        self.write("LISTTAGS", "")
        r = self.wait_response("LISTTAGS")

        self.stub_tagconfigs(r[1])

        self.write("WATCHCONFIGS", "")
        self.write("CONFIGS", [])
        self.prot_configs(self.wait_response("CONFIGS")[1])

        self.prot_newtags(r[1])

        log.debug("FINAL CONFIG:\n%s" % pp.pformat(self.config))
        log.debug("FINAL TAG CONFIG:\n%s" % pp.pformat(self.tag_config))

        # We've got the config, and the tags, go ahead and
        # fire up curses.

        log.debug("Starting curses.")
        self.screen = Screen(self.input_queue, self.callbacks)
        self.screen.refresh()

        self.glog_handler = GraphicalLog(self.callbacks, self.screen)
        rootlog = logging.getLogger()
        rootlog.addHandler(self.glog_handler)

        # Flush out any pre-graphical errors
        for err in self.early_errors:
            log.error(err)

        # We know we're going to want at least these attributes for
        # all stories, as they're part of the fallback format string.

        needed_attrs = [ "title", "canto-state", "link", "enclosures" ]

        # Make sure we grab attributes needed for the story
        # format and story format.

        for attrlist in [ self.config["story"]["format_attrs"],\
                self.config["taglist"]["search_attributes"] ]:
            for sa in attrlist:
                if sa not in needed_attrs:
                    needed_attrs.append(sa)

        self.write("AUTOATTR", needed_attrs)

        item_tags = [ t.tag for t in self.vars["curtags"]]

        # Start watching all given tags.
        self.write("WATCHTAGS", item_tags)

        # Get current items
        for tag in item_tags:
            self.write("ITEMS", [ tag ])

        # Holster for future updated tags.
        self.updates = []

    def wait_response(self, cmd):
        log.debug("waiting on %s" % cmd)
        while True:
            r = self.backend.responses.get()
            if r[0] == cmd:
                return r
            else:
                log.debug("waiting: %s != %s" % (r[0], cmd))

    def write(self, cmd, args, conn=0):
        if not self.disconn:
            self.backend.write(cmd, args, conn)
        else:
            log.debug("Disconnected. Discarding %s - %s" % (cmd, args))

    def prio_write(self, cmd, args):
        self.write(cmd, args, 1)

    def disconnected(self):
        self.disconn = CONN_NEED_NOTIFY

    def reconnected(self):
        self.reconn = CONN_NEED_NOTIFY

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

        strtags = [ tag.tag for tag in self.vars["alltags"] ]

        # Strip items no longer relevant
        for item in val[:]:
            if item not in strtags:
                val.remove(item)

        # Ensure all tags are inluded
        for tag in strtags:
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
        if type(val) == int and val >= -1 and val < 255:
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

                    if not self.glog_handler:
                        self.early_errors.append(err)
                        log.error("Will display " + err)
                    else:
                        log.error(err)

                    changes[key] = d[key]
                    c[key] = d[key]

        return changes, deletions

    # configs accepts any changes, calls the opt_change hooks and
    # if write is set, sends those changes to the daemon. It's
    # called both when receving CONFIGS from the daemon and when
    # we change opts internally (thus the write flag).

    # Note that changes are the only ones propagated through hooks
    # because they are a superset of deletions (i.e. a deletion
    # counts as a change).

    def prot_configs(self, given, write = False):
        log.debug("prot_configs given: %s" % given)

        if "tags" in given:
            for tag in list(given["tags"].keys()):
                ntc = given["tags"][tag]
                tc = self.tag_config[tag]

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

    def prot_attributes(self, d):
        call_hook("curses_attributes", [ d ])

    def prot_items(self, updates):
        # Daemon should now only return with one tag in an items response

        tag = list(updates.keys())[0]

        if self.item_tag == None or self.item_tag.tag != tag:
            self.item_tag = None
            self.item_buf = []
            self.item_removes = []
            self.item_adds = []
            for have_tag in self.vars["alltags"]:
                if have_tag.tag == tag:
                    self.item_tag = have_tag
                    break

            # Shouldn't happen
            else:
                return

        self.item_buf.extend(updates[tag])

        # Add new items.
        for id in updates[tag]:
            if id not in self.item_tag.get_ids():
                self.item_adds.append(id)

    def prot_itemsdone(self, empty):
        unprotect = {"auto":[]}

        if self.item_tag == None:
            return

        self.item_tag.add_items(self.item_adds)

        # Eliminate discarded items. This has to be done here, so we have
        # access to all of the items given in the multiple ITEM responses.

        for id in self.item_tag.get_ids():
            if id not in self.vars["protected_ids"] and \
                    id not in self.item_buf:
                self.item_removes.append(id)

        self.item_tag.remove_items(self.item_removes)

        for id in self.item_removes:
            unprotect["auto"].append(id)

        # If we're using the maintain update style, reorder the feed
        # properly. Append style requires no extra work (add_items does
        # it by default).

        if self.config["update"]["style"] == "maintain":
            log.debug("Re-ordering items (update style maintain)")
            self.item_tag.reorder(self.item_buf)

        self.item_tag = None
        self.item_buf = []
        self.item_removes = []
        self.item_adds = []

        if unprotect["auto"]:
            self.write("UNPROTECT", unprotect)

    def prot_tagchange(self, tag):
        if tag not in self.updates:
            self.updates.append(tag)

    # This function is basically an early version of prot_newtags
    # that creates the relevant data structures, without evaluating
    # tags and relying on subsequent config validation.

    def stub_tagconfigs(self, tags):
        for tag in tags:
            # Create tag configs.
            if tag not in self.tag_config:
                log.debug("Using default tag config for %s" % tag)
                self.tag_config[tag] = self.tag_template_config.copy()

            # Create initial Tag objects so alltags is properly populated.
            # This allows us to properly validate tagorder.

            # We check that one doesn't already exist so that, if we're
            # reconnecting, we don't end up with multiple Tag objects for each
            # tag.

            if tag not in [ t.tag for t in self.vars["alltags"] ]:
                Tag(tag, self.callbacks)

    # Process new tags.

    def prot_newtags(self, tags):

        c = self.get_conf()

        for tag in tags:
            if tag not in [ t.tag for t in self.vars["alltags"] ]:
                log.info("New tag %s" % tag)
                Tag(tag, self.callbacks)

                # If we don't have configuration for this
                # tag already, substitute the default template.

                if tag not in self.tag_config:
                    log.debug("Using default tag config for %s" % tag)
                    self.tag_config[tag] = self.tag_template_config.copy()

            if tag not in c["tagorder"]:
                c["tagorder"] = self.config["tagorder"] + [ tag ]

        self.set_conf(c)
        self.eval_tags()

    def prot_deltags(self, tags):

        c = self.get_conf()

        for tag in tags:
            strtags = [ t.tag for t in self.vars["alltags"] ]
            if tag in strtags:
                new_alltags = self.vars["alltags"]

                # Allow Tag obj to cleanup hooks.
                tagobj = new_alltags[strtags.index(tag)]
                tagobj.die()

                # Remove it from alltags.
                del new_alltags[strtags.index(tag)]
                self.set_var("alltags", new_alltags)
            else:
                log.warn("Got DELTAG for non-existent tag!")

            if tag in c["tagorder"]:
                c["tagorder"] = [ x for x in self.config["tagorder"] if x != tag ]

        self.set_conf(c)

        self.eval_tags()

    def prot_except(self, exception):
        log.error("%s" % exception)

    def prot_errors(self, errors):
        for key in list(errors.keys()):
            val = errors[key][1][0]
            symptom = errors[key][1][1]
            log.error("%s = %s : %s" % (key, val, symptom))

    def prot_info(self, info):
        log.info("%s" % info)

    def eval_tags(self):
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

        # If evaluated tags differ, we need to refresh.

        if prevtags != self.vars["curtags"] and self.screen:
            log.debug("Evaluated Tags Changed: %s" % [ t.tag for t in self.vars["curtags"]])
            call_hook("curses_eval_tags_changed", [])

    def set_var(self, tweak, value):
        # We only care if the value is different, or it's a message
        # value, which should always cause a fresh message display,
        # even if it's the same error as before.

        if self.vars[tweak] != value:

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
                            self.prot_tagchange(tag.tag)

                if value and hasattr(value, "id"):
                    # protected_ids just tells the prot_items to not allow
                    # this item to have it's auto protection stripped.

                    self.vars["protected_ids"].append(value.id)

                    # Set an additional protection, filter-immune so hardened
                    # filters won't eliminate it.

                    self.write("PROTECT", { "filter-immune" : [ value.id ] })

            self.vars[tweak] = value

            call_hook("curses_var_change", [{ tweak : value }])

    def get_var(self, tweak):
        if tweak in self.vars:
            return self.vars[tweak]
        raise Exception("Unknown variable: %s" % (tweak,))

    # Overall configuration operation functions. The paradigm is that internal
    # code can "get" the conf, which is a copy of the real conf, modify it,
    # then "set" the conf which will properly process the changes.

    def set_conf(self, conf):
        self.prot_configs({"CantoCurses" : conf }, True)

    def get_conf(self):
        return eval(repr(self.config), {}, {})

    def set_tag_conf(self, tag, conf):
        self.prot_configs({ "tags" : { tag.tag : conf } }, True)

    def get_tag_conf(self, tag):
        return eval(repr(self.tag_config[tag.tag]), {}, {})

    def _get_opt(self, option, d):
        valid, value = access_dict(d, option)
        if not valid:
            return None
        return value

    def _set_opt(self, option, value, d):
        assign_to_dict(d, option, value)

    def set_opt(self, option, value):
        c = self.get_conf()
        self._set_opt(option, value, c)
        self.set_conf(c)

    def get_opt(self, option):
        c = self.get_conf()
        return  self._get_opt(option, c)

    def set_tag_opt(self, tag, option, value):
        tc = self.get_tag_conf(tag)
        self._set_opt(option, value, tc)
        self.set_tag_conf(tag, tc)

    def get_tag_opt(self, tag, option):
        tc = self.get_tag_conf(tag)
        return self._get_opt(option, tc)

    def opt(self, args):
        t, r = self._first_term(args,
                lambda : self.screen.input_callback("opt: "))
        if not t:
            return (False, None, None)

        # Ensure that that option exists. We just use self.config because we
        # know we're not changing any values.

        try:
            self._get_opt(t, self.config)
            return (True, t, r)
        except:
            log.error("Unknown option: %s" % t)
            return (False, None, None)

    @command_format([("opt","opt")])
    def cmd_toggle(self, **kwargs):
        c = self.get_conf()

        val = self._get_opt(kwargs["opt"], c)

        if type(val) != bool:
            log.error("Option %s isn't boolean." % kwargs["opt"])
            return

        self._set_opt(kwargs["opt"], not val, c)
        self.set_conf(c)

    def switch_tags(self, tag1, tag2):
        c = self.get_conf()

        t1_idx = c["tagorder"].index(tag1.tag)
        t2_idx = c["tagorder"].index(tag2.tag)

        c["tagorder"][t1_idx] = tag2.tag
        c["tagorder"][t2_idx] = tag1.tag

        self.set_conf(c)

        self.eval_tags()

    # This accepts arbitrary strings, but gives the right prompt.
    def transform(self, args):
        if not args:
            args = self.screen.input_callback("transform: ")
        return (True, args, None)

    # Setup a permanent, config based transform.
    @command_format([("transform","transform")])
    def cmd_transform(self, **kwargs):
        d = { "defaults" : { "global_transform" : kwargs["transform"] } }
        self.write("SETCONFIGS", d)
        self._refresh()

    # Setup a temporary, per socket transform.
    @command_format([("transform","transform")])
    def cmd_temp_transform(self, **kwargs):
        self.write("TRANSFORM", kwargs["transform"])
        self._refresh()

    @command_format([])
    def cmd_reconnect(self, **kwargs):
        self.backend.reconnect()

    @command_format([])
    def cmd_refresh(self, **kwargs):
        self._refresh()

    def _refresh(self):
        for tag in self.vars["curtags"]:
            tag.reset()
            self.write("ITEMS", [ tag.tag ])

    def winch(self):
        self.winched = True

    def tick(self):
        self.ticked = True

    def do_tick(self):
        self.ticked = False

        if not self.config["update"]["auto"]["enabled"]:
            return

        if self.update_interval <= 0:
            if self.updates:
                self.write("ITEMS", self.updates)

            self.update_interval =\
                    self.config["update"]["auto"]["interval"]
            self.updates = []
        else:
            self.update_interval -= 1

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        return self.screen.key(k)

    @command_format([("key", "named_key"),("cmdstring","string_or_not")])
    def cmd_bind(self, **kwargs):
        if not self.screen.bind(kwargs["key"], kwargs["cmdstring"]) and\
            not self.bind(kwargs["key"], kwargs["cmdstring"]):
            log.info("%s is unbound." % (kwargs["key"],))

    @command_format([("tags","string_or_not")])
    def cmd_tagregex(self, **kwargs):
        c = self.get_conf()
        if not kwargs["tags"]:
            log.info("tags = %s" % c["tags"])
        else:
            c["tags"] = kwargs["tags"]
        self.set_conf(c)
        self.eval_tags()

    def cmdescape(self, cmd):
        escaped = False
        r = ""
        for c in cmd:
            if escaped:
                r += c
                escaped = False
            elif c == "\\":
                escaped = True
            else:
                r += c
        return r.rstrip()

    def cmdsplit(self, cmd):
        r = escsplit(cmd, " &")

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

#    def run(self):
#        import cProfile
#        cProfile.runctx("self._run()", globals(), locals(), "canto-out")

    def run(self):
        # Priority commands / tuples allow a single user inputed string to
        # actually break down into multiple actions.

        priority = []
        command_string = []

        while True:
            if self.ticked:
                self.do_tick()

            # Turn signals into commands:
            if self.reconn == CONN_NEED_NOTIFY:
                priority.insert(0, ("INFO", self.reconnect_message))
                self.disconn = 0
                self.reconn = CONN_NOTIFIED
                self.daemon_init()
            elif self.disconn == CONN_NEED_NOTIFY:
                priority.insert(0, ("EXCEPT", self.disconnect_message))
                self.reconn = 0
                self.disconn = CONN_NOTIFIED
            if self.winched:
                self.winched = False
                # CMD because it's handled lower, by Screen
                priority.insert(0, ("CMD", "resize"))

            if priority:
                cmd = priority[0]
                priority = priority[1:]
            elif command_string:
                cmd = command_string[0]
                command_string = command_string[1:]
            else:
                cmd = None

                try:
                    cmd = self.input_queue.get(True, 0.1)
                except Empty:
                    pass

                try:
                    if not cmd:
                        cmd = self.backend.prio_responses.get(True, 0.1)
                except Empty:
                    pass

                try:
                    if not cmd:
                        cmd = self.backend.responses.get(True, 0.1)
                except Empty:
                    continue

            if cmd[0] == "KEY":
                resolved = self.key(cmd[1])
                if not resolved:
                    continue
                cmd = ("CMD", resolved)

            # User command
            if cmd[0] == "CMD":
                log.debug("CMD: %s" % (cmd[1],))

                # Sub in a user command on the fly.
                if cmd[1] == "command":
                    cmd = ("CMD", self.screen.input_callback(":"))
                    log.debug("command resolved to: %s" % cmd[1])

                cmds = self.cmdsplit(cmd[1])

                # If this is actually multiple commands,
                # then append them to the priority queue
                # and continue to execute them one at a time.

                if len(cmds) > 1:
                    log.debug("single command split into: %s" % cmds)
                    command_string.extend([("CMD", c) for c in cmds])
                    continue

                if " " in cmd[1]:
                    basecmd, args = cmd[1].split(" ", 1)
                else:
                    basecmd = cmd[1]
                    args = ""

                if basecmd in self.aliases:
                    log.debug("resolved '%s' to '%s'" %\
                            (basecmd, self.aliases[basecmd]))
                    basecmd = self.aliases[basecmd]

                fullcmd = basecmd
                if args:
                    fullcmd += " " + args

                fullcmd = self.cmdescape(fullcmd)

                if fullcmd in ["quit", "exit"]:
                    rootlog = logging.getLogger()
                    rootlog.removeHandler(self.glog_handler)
                    call_hook("curses_exit", [])
                    self.screen.exit()
                    if self.config["kill_daemon_on_exit"]:
                        self.write("DIE", "")
                    self.backend.exit()
                    return

                r = self.command(fullcmd)
                if r == None:
                    r = self.screen.command(fullcmd)

                if r == False:
                    log.debug("Command string canceled: %s" %\
                            (command_string,))
                    command_string = []
            else:
                protfunc = "prot_" + cmd[0].lower()
                if hasattr(self, protfunc):
                    getattr(self, protfunc)(cmd[1])

            if self.vars["needs_refresh"]:
                log.debug("Needed refresh")
                self.screen.refresh()
                self.vars["needs_refresh"] = False

            if self.vars["needs_redraw"]:
                log.debug("Needed redraw")
                self.screen.redraw()
                self.vars["needs_redraw"] = False

            if self.vars["needs_resize"]:
                self.winched = True
                self.vars["needs_resize"] = False

    def get_opt_name(self):
        return "main"
