# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.plugins import Plugin
from command import CommandHandler, command_format
from html import html_entity_convert, char_ref_convert
from screen import Screen
from tag import Tag

import logging
import curses
import re

log = logging.getLogger("GUI")

class GuiPlugin(Plugin):
    pass

class CantoCursesGui(CommandHandler):
    def __init__(self, backend):
        CommandHandler.__init__(self)
        self.plugin_class = GuiPlugin
        self.backend = backend
        self.screen = None

        # Variables that affect the overall operation.

        self.vars = {
            "reader_item" : None,
            "reader_offset" : 0,
            "selected" : None,
            "curtags" : [],
            "alltags" : [],
            "needs_refresh" : False,
            "needs_redraw" : False,
            "needs_deferred_refresh" : False,
            "needs_deferred_redraw" : False,
            "update_interval" : 0,
            "protected_ids" : [],
            "transforms" : [],
        }

        self.callbacks = {
            "set_var" : self.set_var,
            "get_var" : self.get_var,
            "set_opt" : self.set_opt,
            "get_opt" : self.get_opt,
            "write" : self.backend.write
        }

        self.keys = {
            ":" : "command",
            "q" : "quit"
        }

        self.config = {
            "browser" : "firefox %u",
            "txt_browser" : False,
            "tags" : r".*",
            "update.auto.interval" : 60,
            "reader.maxwidth" : 0,
            "reader.maxheight" : 0,
            "reader.float" : True,
            "reader.align" : "topleft",
            "reader.enumerate_links" : False,
            "reader.show_description" : True,
            "taglist.maxwidth" : 0,
            "taglist.maxheight" : 0,
            "taglist.float" : False,
            "taglist.align" : "neutral",
            "taglist.tags_enumerated" : False,
            "taglist.hide_empty_tags" : True,
            "story.enumerated" : False,
            "input.maxwidth" : 0,
            "input.maxheight" : 0,
            "input.float" : False,
            "input.align" : "bottom",

            "main.key.colon" : "command",
            "main.key.q" : "quit",
            "main.key.\\" : "refresh",

            "taglist.key.space" : "foritem & item-state read & reader",
            "taglist.key.g" : "foritems & goto & item-state read & clearitems",
            "taglist.key.E" : "toggle-opt taglist.tags_enumerated",
            "taglist.key.e" : "toggle-opt story.enumerated",
            "taglist.key.R" : "item-state read *",
            "taglist.key.U" : "item-state -read *",
            "taglist.key.r" : "tag-state read",
            "taglist.key.u" : "tag-state -read",
            "taglist.key.npage" : "page-down",
            "taglist.key.ppage" : "page-up",
            "taglist.key.down" : "rel-set-cursor 1",
            "taglist.key.up" : "rel-set-cursor -1",
            "taglist.key.C-u" : "unset-cursor",

            "reader.key.space" : "destroy",
            "reader.key.d" : "toggle-opt reader.show_description",
            "reader.key.l" : "toggle-opt reader.enumerate_links",
            "reader.key.g" : "goto",
            "reader.key.down" : "scroll-down",
            "reader.key.up" : "scroll-up",
            "reader.key.npage" : "page-down",
            "reader.key.ppage" : "page-up",

            "color.0" : curses.COLOR_WHITE,
            "color.1" : curses.COLOR_BLUE,
            "color.2" : curses.COLOR_YELLOW,
            "color.3" : curses.COLOR_BLUE,
            "color.4" : curses.COLOR_GREEN,
            "color.5" : curses.COLOR_MAGENTA,
        }

        # Configuration options that, on change, require a refresh, in
        # regexen.

        self.refresh_configs = [re.compile(x) for x in\
                [ ".*enumerated", ".*hide_empty_tags",
                    ".*show_description", ".*enumerate_links" ]]

        # Configuration options that, on change, require an ncurses
        # reset or windows to be redone.

        self.winch_configs = [re.compile(x) for x in\
                [ "color\.*", ".*align", ".*float", ".*maxheight",
                    ".*maxwidth"]]

        self.backend.write("WATCHCONFIGS", u"")

        self.backend.write("CONFIGS", [])
        self.prot_configs(self.wait_response("CONFIGS")[1])

        log.debug("FINAL CONFIG:\n%s" % self.config)

        self.backend.write("LISTFEEDS", u"")
        r = self.wait_response("LISTFEEDS")
        self.tracked_feeds = r[1]

        self.backend.write("LISTTRANSFORMS", u"")
        r = self.wait_response("LISTTRANSFORMS")
        self.vars["transforms"] = r[1]

        # Initial tag populate.

        self.updates = []

        for tag, URL in self.tracked_feeds:
            log.info("Tracking [%s] (%s)" % (tag, URL))
            t = Tag(tag, self.callbacks)

        self.eval_tags()
        item_tags = [ t.tag for t in self.vars["curtags"]]

        # We've got the config, and the tags, go ahead and
        # fire up curses.

        log.debug("Starting curses.")
        self.screen = Screen(self.backend.responses, self.callbacks)
        self.screen.refresh()

        for tag in item_tags:
            self.backend.write("ITEMS", [tag])

        # Start watching all given tags.
        self.backend.write("WATCHTAGS", item_tags)

        # Start watching for new and deleted tags.
        self.backend.write("WATCHNEWTAGS", [])
        self.backend.write("WATCHDELTAGS", [])

    def wait_response(self, cmd):
        log.debug("waiting on %s" % cmd)
        while True:
            r = self.backend.responses.get()
            if r[0] == cmd:
                return r
            else:
                log.debug("waiting: %s != %s" % (r[0], cmd))

    def _val_bool(self, attr):
        if type(self.config[attr]) != bool:
            if self.config[attr].lower() == "true":
                self.config[attr] = True
            elif self.config[attr].lower() == "false":
                self.config[attr] = False
            else:
                self.config[attr] = self.def_config[attr]
                log.error("%s must be boolean. Resetting to %s" %
                        (attr, self.def_config[attr]))

    def _val_uint(self, attr):
        if type(self.config[attr]) != int:
            try:
                self.config[attr] = int(self.config[attr])
            except:
                self.config[attr] = self.def_config[attr]
                log.error("%s must be integer. Resetting to %s" %
                        (attr, self.def_config[attr]))
        elif int < 0:
            self.config[attr] = self.def_config[attr]
            log.error("%s must be >= 0. Resetting to %s" %
                    (attr, self.def_config[attr]))

    def _val_color(self, attr): 
        if type(self.config[attr]) != int:
            try:
                self.config[attr] = int(self.config[attr])
            except:
                # Convert natural color into curses color #
                if self.config[attr] == "pink":
                    self.config[attr] == "magenta"
                for color_attr in dir(curses):
                    if color_attr.startswith("COLOR_") and\
                            self.config[attr] == color_attr[6:].lower():
                        self.config[attr] = getattr(curses, color_attr)
                        return

        # If we got an int from above, make sure it's ok.
        if type(self.config[attr]) == int:
            if -1 <= self.config[attr] <= 255:
                if self.config[attr] == -1 and not attr.endswith("bg"):
                    log.error("Only background elements can be -1.")
                else:
                    return

        # Couldn't parse, revert.
        if attr in self.def_config:
            log.error("Reverting %s to default: %s" %\
                    (attr, self.def_config[attr]))
            self.config[attr] = self.def_config[attr]
        else:
            del self.config[attr]

    def validate_config(self):
        self._val_uint("update.auto.interval")
        self._val_bool("reader.show_description")
        self._val_bool("reader.enumerate_links")
        self._val_bool("story.enumerated")
        self._val_bool("taglist.tags_enumerated")
        self._val_bool("taglist.hide_empty_tags")
        self._val_bool("txt_browser")

        # Make sure colors are all integers.
        for attr in [k for k in self.config.keys() if k.startswith("color.")]:
            self._val_color(attr)

        # Make sure various window configurations make sense.
        for wintype in [ "reader", "input", "taglist" ]:
            # Ensure float attributes are boolean
            float_attr = wintype + ".float"
            self._val_bool(float_attr)

            # Ensure alignment jive with float.

            float_aligns = [ "topleft", "topright", "center", "neutral",\
                    "bottomleft", "bottomright"]

            tile_aligns = [ "top", "left", "bottom", "right", "neutral" ]

            align_attr = wintype + ".align"

            if self.config[float_attr]:
                if self.config[align_attr] not in float_aligns:

                    # Translate tile aligns to float aligns.
                    if self.config[align_attr] in tile_aligns:
                        if self.config[align_attr] in ["top","bottom"]:
                            self.config[align_attr] += "left"
                        elif self.config[align_attr] in ["left","right"]:
                            self.config[align_attr] = "top" +\
                                    self.config[align_attr]
                        log.info("Translated %s alignment for float: %s" %
                                (align_attr, self.config[align_attr]))
                    else:
                        # Got nonsense, revert to default.
                        err = "%s unknown float alignment. Resetting to "
                        if self.def_config[align_attr] not in float_aligns:
                            self.config[float_attr] = False
                            err += "!float/"

                        self.config[align_attr] = self.def_config[align_attr]
                        err += self.def_config[align_attr]
                        log.error(err % align_attr)
            # !floating
            else:
                # No translation since it would be ambiguous.
                if self.config[align_attr] not in tile_aligns:
                    err = "%s unknown nonfloat alignment. Resetting to "
                    if self.def_config[align_attr] in float_aligns:
                        self.config[float_attr] = True
                        err += "float/"
                    self.config[align_attr] = self.def_config[align_attr]
                    err += self.def_config[align_attr]
                    log.error(err % align_attr)

            # Make sure size restrictions are positive integers
            for subattr in [".maxheight", ".maxwidth"]:
                self._val_uint(wintype + subattr)

    def eval_tags(self):
        prevtags = self.vars["curtags"]
        self.vars["curtags"] = []

        r = re.compile(self.config["tags"])
        for tag in self.vars["alltags"]:
            if r.match(tag.tag):
                self.vars["curtags"].append(tag)

        if not self.vars["curtags"]:
            log.warn("NOTE: Current 'tags' setting eliminated all tags!")

        # If evaluated tags differ, we need to refresh.

        if prevtags != self.vars["curtags"] and self.screen:
            log.debug("Evaluated tags changed, refresh.")
            self._refresh()

    def prot_configs(self, given):
        if "CantoCurses" not in given:
            return

        self.def_config = self.config.copy()

        for k in given["CantoCurses"]:
            self.config[k] = given["CantoCurses"][k]

        # Need to validate to allow for content changes.
        self.validate_config()

        changed_opts = []

        for k in self.config:
            if k not in self.def_config or\
                    self.def_config[k] != self.config[k]:
                changed_opts.append(k)

        for k in self.def_config:
            if k not in self.config:
                changed_opts.append(k)

        self.check_opt_refresh(changed_opts)

    def prot_attributes(self, d):
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

    def prot_items(self, updates):
        needed_attrs = {}
        unprotect = {"auto":[]}

        for tag in updates:
            for have_tag in self.vars["alltags"]:
                if have_tag.tag == tag:

                    # Eliminate discarded items.
                    for id in have_tag.get_ids():
                        if id not in self.vars["protected_ids"] and \
                                id not in updates[tag]:
                            have_tag.remove(id)
                            unprotect["auto"].append(id)

                    # Add new items.
                    for id in updates[tag]:
                        if id not in have_tag.get_ids():
                            have_tag.append(id)

                            story = have_tag.get_id(id)
                            needed_attrs[story.id] = story.needed_attributes()

        if needed_attrs:
            self.backend.write("ATTRIBUTES", needed_attrs)

        if unprotect:
            self.backend.write("UNPROTECT", unprotect)

        self.vars["needs_refresh"] = True

    def prot_tagchange(self, tag):
        if tag not in self.updates:
            self.updates.append(tag)

    def prot_newtags(self, tags):
        for tag in tags:
            if tag not in [ t.tag for t in self.vars["alltags"] ]:
                log.debug("Adding tag %s" % tag)
                Tag(tag, self.callbacks)
            else:
                log.warn("Got NEWTAG for already existing tag!")
        self.eval_tags()

    def prot_deltags(self, tags):
        for tag in tags:
            strtags = [ t.tag for t in self.vars["alltags"] ]
            if tag in strtags:
                del self.vars["alltags"][strtags.index(tag)]
                break
        self.eval_tags()

    def var(self, args):
        t, r = self._first_term(args,\
                lambda : self.screen.input_callback("var: "))
        if t in self.vars:
            return (True, t, r)
        log.error("Unknown variable: %s" % t)
        return (False, None, None)

    @command_format([("var","var")])
    def cmd_set(self, **kwargs):
        if self.vars[kwargs["var"]] in [ True, False]:
            self.set_var(kwargs["var"], True)
        else:
            log.error("Variable %s is not boolean." % kwargs["var"])

    @command_format([("var","var")])
    def cmd_unset(self, **kwargs):
        if self.vars[kwargs["var"]] in [True, False]:
            self.set_var(kwargs["var"], False)
        else:
            log.error("Variable %s is not boolean." % kwargs["var"])

    @command_format([("var","var")])
    def cmd_toggle(self, **kwargs):
        var = kwargs["var"]
        self.set_var(var, not self.get_var(var))

    def set_var(self, tweak, value):
        if self.vars[tweak] != value:
            # Tweak specific logic
            if tweak in [ "selected", "reader_item" ]:
                if self.vars[tweak]:
                    self.vars["protected_ids"].remove(self.vars[tweak].id)
                if value:
                    self.vars["protected_ids"].append(value.id)

            self.vars[tweak] = value

    def get_var(self, tweak):
        if tweak in self.vars:
            return self.vars[tweak]
        return None

    def opt(self, args):
        t, r = self._first_term(args,
                lambda : self.screen.input_callback("opt: "))
        if t in self.config:
            return (True, t, r)
        log.error("Unknown option: %s" % t)
        return (False, None, None)

    @command_format([("opt","opt")])
    def cmd_toggle_opt(self, **kwargs):
        opt = kwargs["opt"]
        if opt not in self.config:
            log.error("Unknown option: %s" % opt)
            return
        if type(self.config[opt]) != bool:
            log.error("Option %s isn't boolean." % opt)
            return
        self.set_opt(opt, not self.config[opt])

    # Pretend to SIGWINCH (causing screen to regenerate
    # all windows) if any of the refresh_configs have changed.

    def check_opt_refresh(self, changed_opts):
        if not self.screen:
            return

        should_winch = False
        for opt in changed_opts:
            for regx in self.winch_configs:
                if regx.match(opt):
                    should_winch = True

        # We only winch once. It would seem that WINCH would make the next loop
        # (refresh configs) moot and we should return.  However, if we block (as
        # on input), then the refresh will take place immediately while the
        # winch has to require queue action.

        if should_winch:
            self.winch()

        for opt in changed_opts:
            for regx in self.refresh_configs:
                if regx.match(opt):
                    log.info("COR: matched %s" % opt)
                    self.screen.refresh()
                    return

    def set_opt(self, option, value):

        # XXX : Note that set_opt performs *no* validation and expects its
        # (internal) caller to have ensured that it's valid.

        if option not in self.config or self.config[option] != value:
            self.config[option] = value
            self.check_opt_refresh([option])
            self.backend.write("SETCONFIGS",\
                    { "CantoCurses" : { option : unicode(value) } })

    def get_opt(self, option):
        if option in self.config:
            return self.config[option]
        return None

    def transform(self, args):
        if not args:
            args = self.screen.input("transform: ")
        return (True, args, None)

    @command_format([("transform","transform")])
    def cmd_transform(self, **kwargs):
        self.backend.write("SETCONFIGS",\
                    { "defaults" :
                        { "global_transform" : kwargs["transform"] }
                    })
        self._refresh()

    def winch(self):
        self.backend.responses.put(("CMD", "resize"))

    def tick(self):
        if self.vars["update_interval"] == 0:
            if self.updates:
                # TODO: use self.updates or self.vars["curtags"] based on config
                self.backend.write("ITEMS",\
                        [ t.tag for t in self.vars["curtags"]])
                self.vars["update_interval"] =\
                        self.config["update.auto.interval"]
                self.updates = []
        else:
            self.vars["update_interval"] -= 1

    @command_format([])
    def cmd_refresh(self, **kwargs):
        self._refresh()

    def _refresh(self):
        self.backend.write("ITEMS", [ t.tag for t in self.vars["curtags"]])

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        return self.screen.key(k)

    # Search for unescaped & to split up multiple commands.
    def cmdsplit(self, cmd):
        r = []
        escaped = False
        acc = ""
        for c in cmd:
            if escaped:
                acc += c
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == "&":
                r.append(acc)
                acc = ""
            else:
                acc += c
        r.append(acc)

        # lstrip all commands because we
        # want to use .startswith instead of a regex.
        return [ s.lstrip() for s in r ]

    def run(self):
        # Priority commands allow a single
        # user inputed string to actually
        # break down into multiple actions.
        priority_commands = []

        while True:
            if priority_commands:
                cmd = ("CMD", priority_commands[0])
                priority_commands = priority_commands[1:]
            else:
                cmd = self.backend.responses.get()

            if cmd[0] == "KEY":
                resolved = self.key(cmd[1])
                if not resolved:
                    continue
                cmd = ("CMD", resolved)

            # User command
            if cmd[0] == "CMD":
                log.debug("CMD: %s" % cmd[1])

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
                    priority_commands.extend(cmds)
                    continue

                if cmd[1] in ["quit", "exit"]:
                    self.screen.exit()
                    self.backend.exit()
                    return

                # Variable Operations
                if not self.command(cmd[1]):
                    self.screen.command(cmd[1])

            protfunc = "prot_" + cmd[0].lower()
            if hasattr(self, protfunc):
                getattr(self, protfunc)(cmd[1])

            if self.vars["needs_refresh"]:
                log.debug("Needed refresh")
                self.screen.refresh()
                self.vars["needs_refresh"] = False
                self.vars["needs_redraw"] = False
            elif self.vars["needs_redraw"]:
                log.debug("Needed redraw")
                self.screen.redraw()
                self.vars["needs_redraw"] = False

            if self.vars["needs_deferred_refresh"]:
                self.vars["needs_deferred_refresh"] = False
                self.vars["needs_deferred_redraw"] = False
                self.vars["needs_refresh"] = True
            elif self.vars["needs_deferred_redraw"]:
                self.vars["needs_deferred_redraw"] = False
                self.vars["needs_redraw"] = True

    def get_opt_name(self):
        return "main"
