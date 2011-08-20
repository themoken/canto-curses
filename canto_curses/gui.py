# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

COMPATIBLE_VERSION = 0.3

from canto_next.hooks import call_hook, on_hook
from canto_next.plugins import Plugin
from canto_next.remote import assign_to_dict, access_dict
from canto_next.encoding import decoder
from canto_next.format import escsplit

from command import CommandHandler, command_format
from html import html_entity_convert, char_ref_convert
from story import DEFAULT_FSTRING
from text import ErrorBox, InfoBox
from screen import Screen
from tag import Tag, DEFAULT_TAG_FSTRING

from Queue import Empty
import logging
import curses
import sys
import re

log = logging.getLogger("GUI")

class GuiPlugin(Plugin):
    pass

class CantoCursesGui(CommandHandler):
    def __init__(self, backend):
        CommandHandler.__init__(self)

        self.plugin_class = GuiPlugin
        self.update_plugin_lookups()

        self.backend = backend
        self.screen = None

        self.update_interval = 0

        self.disconnect_message =\
""" Disconnected!

Please restart the daemon and use :reconnect.

Until reconnected, it will be impossible to fetch any information, and
any state changes will be lost.

Press [space] to close."""

        self.reconnect_message =\
""" Successfully Reconnected!

Press [space] to close."""

        # Asynchronous notification flags
        self.disconn = False
        self.reconn = False
        self.ticked = False
        self.winched = False

        # Variables that affect the overall operation.

        self.vars = {
            "location" : self.backend.location_args,
            "error_msg" : "No error. Press [space] to close.",
            "info_msg" : "No info. Press [space] to close.",
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
            "write" : self.backend.write
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

            "tag" : { "format" : self.validate_string },

            "update" :
            {
                "style" : self.validate_update_style,
                "auto" : { "interval" : self.validate_uint }
            },

            "reader" :
            {
                "window" : self.validate_window,
                "key" : self.validate_key,
                "enumerate_links" : self.validate_bool,
                "show_description" : self.validate_bool
            },

            "taglist" :
            {
                "window" : self.validate_window,
                "key" : self.validate_key,
                "tags_enumerated" : self.validate_bool,
                "tags_enumerated_absolute" : self.validate_bool,
                "hide_empty_tags" : self.validate_bool,
                "search_attributes" : self.validate_string_list,
            },

            "story" :
            {
                "enumerated" : self.validate_bool,
                "format" : self.validate_string,
                "format_attrs" : self.validate_string_list,
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
            }
        }

        self.config = {
            "browser" :
            {
                "path" : "firefox %u",
                "text" : False
            },

            "tags" : r"maintag:.*",
            "tagorder" : [],

            "tag" : { "format" : DEFAULT_TAG_FSTRING },

            "update" :
            {
                "style" : "append",
                "auto" : { "interval" : 60 }
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
                "key" :
                {
                    "space" : "destroy",
                    "d" : "toggle reader.show_description",
                    "l" : "toggle reader.enumerate_links",
                    "g" : "goto",
                    "down" : "scroll-down",
                    "up" : "scroll-up",
                    "npage" : "page-down",
                    "ppage" : "page-up",
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
                    "$" : "item-state read t:. 0-.",
                    "/" : "search",
                    "?" : "search-regex",
                    "n" : "next-marked",
                    "p" : "prev-marked",
                    "M" : "item-state -marked *",
                },
            },

            "story" :
            {
                "enumerated" : False,
                "format" : DEFAULT_FSTRING,
                "format_attrs" : [ "title" ],
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
            }
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
                "add" : "remote addfeed",
                "del" : "remote delfeed",
                "list" : "remote listfeeds",
                "q" : "quit",
                "filter" : "transform",
                "sort" : "transform",
        }

        # Make sure that we're not mismatching versions.

        self.backend.write("VERSION", u"")
        r = self.wait_response("VERSION")
        if r[1] != COMPATIBLE_VERSION:
            s = "Incompatible daemon version (%s) detected! Expected: %s" %\
                (r[1], COMPATIBLE_VERSION)
            log.debug(s)
            print s
            sys.exit(-1)
        else:
            log.debug("Got compatible daemon version.")

        # Start watching for new and deleted tags.
        self.backend.write("WATCHNEWTAGS", [])
        self.backend.write("WATCHDELTAGS", [])

        self.backend.write("LISTTAGS", u"")
        r = self.wait_response("LISTTAGS")

        self.stub_tagconfigs(r[1])

        self.backend.write("WATCHCONFIGS", u"")
        self.backend.write("CONFIGS", [])
        self.prot_configs(self.wait_response("CONFIGS")[1], True)

        self.prot_newtags(r[1])

        log.debug("FINAL CONFIG:\n%s" % self.config)
        log.debug("FINAL TAG CONFIG:\n%s" % self.tag_config)

        # We've got the config, and the tags, go ahead and
        # fire up curses.

        log.debug("Starting curses.")
        self.screen = Screen(self.backend.responses, self.callbacks)
        self.screen.refresh()

        item_tags = [ t.tag for t in self.vars["curtags"]]
        for tag in item_tags:
            self.backend.write("ITEMS", [ tag ])

        # Start watching all given tags.
        self.backend.write("WATCHTAGS", item_tags)

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

    def disconnected(self):
        self.disconn = True

    def reconnected(self):
        self.reconn = True

    def validate_uint(self, val, d):
        if type(val) == int and val >= 0:
            return (True, val)
        return (False, False)

    def validate_string(self, val, d):
        if type(val) == unicode:
            return (True, val)
        if type(val) == str:
            return (True, decoder(val))
        return (False, False)

    def validate_bool(self, val, d):
        if val in [ True, False ]:
            return (True, val)
        return (False, False)

    def validate_update_style(self, val, d):
        if val in [ u"maintain", u"append" ]:
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
                return (False, False)

        # Ensure all settings are in their correct range
        if val["border"] not in ["full", "none", "smart"]:
            return (False, False)

        if val["float"] not in [ True, False ]:
            return (False, False)

        for int_setting in ["maxwidth", "maxheight" ]:
            if type(val[int_setting]) != int or val[int_setting] < 0:
                return (False, False)

        float_aligns = [ "topleft", "topright", "center", "neutral",\
                "bottomleft", "bottomright" ]

        tile_aligns = [ "top", "left", "bottom", "right", "neutral" ]

        if val["float"]:
            if val["align"] not in float_aligns:
                return (False, False)
        else:
            if val["align"] not in tile_aligns:
                return (False, False)

        return (True, val)

    # This doesn't validate that the command will actually work, just that the
    # pair is of the correct types.

    def validate_key(self, val, d):
        if type(val) != dict:
            return (False, False)

        for key in val.keys():
            if type(key) != unicode:
                if type(key) == str:
                    newkey = decoder(key)
                    v = val[key]
                    del val[key]
                    val[newkey] = v
                else:
                    return (False, False)

            if type(val[key]) != unicode:
                if type(val[key]) == str:
                    val[key] = decoder(val[key])
                else:
                    return (False, False)

        # For keys, because we don't want to specify each and every possible
        # key explicitly, so we merge in default keys. If a user wants to
        # ignore a default key, he can set it to None and it won't be merged
        # over.

        for key in d.keys():
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
        if type(val) not in [ unicode, str ]:
            return (False, False)

        # See if it's an integer as a string
        try:
            ival = int(val)
            return (True, ival)
        except:
            # Alias pink and magenta
            if val == "pink":
                val = "magenta"

            # Lookup defined curses colors.
            for color_attr in dir(curses):
                if not color_attr.startswith("COLOR_"):
                    continue
                if val.lower() == color_attr[6:].lower():
                    return (True, getattr(curses, color_attr))

        return (False, False)

    def validate_string_list(self, val, d):
        if type(val) != list:
            return (False, False)

        r = []
        for item in val:
            if type(item) == unicode:
                r.append(item)
            elif type(item) == str:
                r.append(decoder(item))
            else:
                return (False, False)

        return (True, r)

    # Recursively validate config c, with validators in v, falling back on d
    # when it failed. Return a dict containing all of the changes actually
    # made.

    # Note that unknown values are detected only to avoid access errors, they
    # are totally ignored and will never get changes processed.

    def validate_config(self, c, d, v):
        changes = {}

        # Sub in non-existent values:

        log.debug("d = %s" % d)

        for key in v.keys():
            if key not in c:
                c[key] = d[key]

        # Validate existing values.

        for key in c.keys():

            # Unknown values, don't validate
            if key not in v:
                continue

            # Key is section, recurse, only add changes if there
            # are actual changes.

            elif type(v[key]) == dict:
                tmp =  self.validate_config(c[key], d[key], v[key])
                if tmp:
                    changes[key] = tmp

            # Key is basic, validate
            else:
                good, val = v[key](c[key], d[key])

                # Value is good, pass on
                if good:
                    if val != d[key]:
                        changes[key] = val
                    c[key] = val

                # Value is bad, revert
                else:
                    changes[key] = d[key]
                    c[key] = d[key]

        return changes

    def prot_configs(self, given, write = False):

        if "tags" in given:
            for tag in given["tags"].keys():
                ntc = given["tags"][tag]
                tc = self.tag_config[tag]

                changes = self.validate_config(ntc, tc, self.tag_validators)

                if changes:
                    call_hook("tag_opt_change", [ { tag : changes } ])
                    self.tag_config = new_tag_config
                    if write:
                        self.backend.write("SETCONFIGS",\
                                { "tags" : { tag : changes }})

        if "CantoCurses" in given:
            new_config = given["CantoCurses"]

            log.debug("given: %s" % given)

            changes = self.validate_config(new_config, self.config,\
                    self.validators)

            log.debug("changes: %s" % changes)

            if changes:
                self.config = new_config
                call_hook("opt_change", [ changes ])

                if write:
                    self.backend.write("SETCONFIGS",\
                            { "CantoCurses" : changes })

    def prot_attributes(self, d):
        atts = {}
        for given_id in d:
            for tag in self.vars["alltags"]:
                item = tag.get_id(given_id)
                if not item:
                    continue

                for k in d[given_id]:
                    a = d[given_id][k]
                    if type(a) == unicode:
                        a = a.replace("\\", "\\\\")
                        a = a.replace("%", "\\%")
                        a = html_entity_convert(a)
                        a = char_ref_convert(a)
                    item.content[k] = a
                atts[item] = d[given_id].keys()

        if atts:
            call_hook("attributes", [ atts ])

    def prot_items(self, updates):
        needed_attrs = {}
        unprotect = {"auto":[]}

        for tag in updates:
            for have_tag in self.vars["alltags"]:
                if have_tag.tag != tag:
                    continue

                adds = []
                removes = []

                # Eliminate discarded items.
                for id in have_tag.get_ids():
                    if id not in self.vars["protected_ids"] and \
                            id not in updates[tag]:
                        removes.append(id)

                # Add new items.
                for id in updates[tag]:
                    if id not in have_tag.get_ids():
                        adds.append(id)

                have_tag.add_items(adds)
                for id in adds:
                    story = have_tag.get_id(id)

                    # We *at least* need title, state, and link, these
                    # will allow us to fall back on the default format string
                    # which relies on these.

                    needed_attrs[id] = [ "title", "canto-state", "link" ]

                    # Make sure we grab attributes needed for the story
                    # format and story format.

                    for attrlist in [ self.config["story"]["format_attrs"],\
                            self.config["taglist"]["search_attributes"] ]:
                        for sa in attrlist:
                            if sa not in needed_attrs[id]:
                                needed_attrs[id].append(sa)

                have_tag.remove_items(removes)
                for id in removes:
                    unprotect["auto"].append(id)

                # If we're using the maintain update style, reorder the feed
                # properly. Append style requires no extra work (add_items does
                # it by default).

                if self.config["update"]["style"] == "maintain":
                    log.debug("Re-ording items (update style maintain)")
                    have_tag.reorder(updates[tag])

        if needed_attrs:
            self.backend.write("ATTRIBUTES", needed_attrs)

        if unprotect["auto"]:
            self.backend.write("UNPROTECT", unprotect)

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

            Tag(tag, self.callbacks)

    # Process new tags, early flag tells us whether we should bother to
    # propagate tagorder changes and eval tags or if we just want to create Tag
    # objects.

    def prot_newtags(self, tags):

        c = self.get_conf()

        for tag in tags:
            if tag not in [ t.tag for t in self.vars["alltags"] ]:
                log.info("Adding tag %s" % tag)
                Tag(tag, self.callbacks)

                # If we don't have configuration for this
                # tag already, substitute the default template.

                if tag not in self.tag_config:
                    log.debug("Using default tag config for %s" % tag)
                    self.tag_config[tag] = self.tag_template_config.copy()
            else:
                log.warn("Got NEWTAG for already existing tag!")

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
        self.set_var("error_msg", "%s" % exception)

    def prot_errors(self, errors):
        self.set_var("error_msg", "%s" % errors)

    def prot_info(self, info):
        self.set_var("info_msg", "%s" % info)

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
            log.debug("Evaluated Tags Changed")
            call_hook("eval_tags_changed", [])

    def set_var(self, tweak, value):
        # We only care if the value is different, or it's a message
        # value, which should always cause a fresh message display,
        # even if it's the same error as before.

        if self.vars[tweak] != value or tweak in [ "error_msg", "info_msg"]:

            # If we're selecting or unselecting a story, then
            # we need to make sure it doesn't disappear.

            if tweak in [ "selected", "reader_item" ]:
                if self.vars[tweak] and hasattr(self.vars[tweak], "id"):

                    # protected_ids just tells the prot_items to not allow
                    # this item to have it's auto protection stripped.

                    self.vars["protected_ids"].remove(self.vars[tweak].id)

                    # Set an additional protection, filter-immune so hardened
                    # filters won't eliminate it.

                    self.backend.write("UNPROTECT",\
                            { "filter-immune" : [ self.vars[tweak].id ] })

                if value and hasattr(value, "id"):
                    self.vars["protected_ids"].append(value.id)
                    self.backend.write("PROTECT",\
                            { "filter-immune" : [ value.id ] })

            self.vars[tweak] = value

            if tweak in [ "error_msg" ] and self.screen:
                self.screen.add_window_callback(ErrorBox)
            elif tweak in [ "info_msg" ] and self.screen:
                self.screen.add_window_callback(InfoBox)

            call_hook("var_change", { tweak : value })

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
        self.prot_config({ "tags" : { tag.tag : conf } }, True)

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
        self.backend.write("SETCONFIGS", d)
        self._refresh()

    # Setup a temporary, per socket transform.
    @command_format([("transform","transform")])
    def cmd_temp_transform(self, **kwargs):
        self.backend.write("TRANSFORM", kwargs["transform"])
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
            self.backend.write("ITEMS", [ tag.tag ])

    def winch(self):
        self.winched = True

    def tick(self):
        self.ticked = True

    def do_tick(self):
        self.ticked = False
        if self.update_interval <= 0:
            if self.updates:
                self.backend.write("ITEMS", self.updates)

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

    def cmdsplit(self, cmd):
        r = escsplit(cmd, "&")

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

        while True:
            if self.ticked:
                self.do_tick()

            # Turn signals into commands:
            if self.reconn:
                log.info("Reconnected.")
                self.reconn = False
                priority.insert(0, ("INFO", self.reconnect_message))
            elif self.disconn:
                log.info("Disconnected.")
                self.disconn = False
                priority.insert(0, ("EXCEPT", self.disconnect_message))

            if self.winched:
                self.winched = False
                # CMD because it's handled lower, by Screen
                priority.insert(0, ("CMD", "resize"))

            if priority:
                cmd = priority[0]
                priority = priority[1:]
            else:
                try:
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
                    priority.extend([("CMD", c) for c in cmds])
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

                if fullcmd in ["quit", "exit"]:
                    self.screen.exit()
                    self.backend.exit()
                    return

                # Variable Operations
                if not self.command(fullcmd):
                    self.screen.command(fullcmd)
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
