# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from command import CommandHandler, command_format, generic_parse_error
from html import html_entity_convert, char_ref_convert
from screen import Screen
from tag import Tag

import logging

log = logging.getLogger("GUI")

class CantoCursesGui(CommandHandler):
    def init(self, backend, do_curses=True):
        self.backend = backend

        # Variables that affect the overall operation.
        # We use the same list for alltags and curtags
        # so that, if curtags isn't set explicity, it
        # automatically equals alltags

        td = []
        self.vars = {
            "reader_item" : None,
            "selected" : None,
            "curtags" : td,
            "alltags" : td,
            "needs_refresh" : False,
            "needs_redraw" : False,
            "needs_deferred_redraw" : False
        }

        callbacks = {
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

        self.def_config = {
            "browser" : "firefox %u",
            "txt_browser" : False,
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
            "input.align" : "bottom"
        }

        self.backend.write("CONFIGS", [ "CantoCurses" ])
        self.config = self.def_config.copy()
        self.config.update(self.wait_response("CONFIGS")[1]["CantoCurses"])
        self.validate_config()

        log.debug("FINAL CONFIG:\n%s" % self.config)

        self.backend.write("LISTFEEDS", u"")
        r = self.wait_response("LISTFEEDS")
        self.tracked_feeds = r[1]

        # Initial tag populate.

        item_tags = []
        for tag, URL in self.tracked_feeds:
            log.info("Tracking [%s] (%s)" % (tag, URL))
            t = Tag(tag, callbacks)
            item_tags.append(tag)

        self.backend.write("ITEMS", item_tags)
        r = self.wait_response("ITEMS")

        for tag in self.vars["alltags"]:
            for item in r[1][tag.tag]:
                tag.append(item)

        # Initial story attribute populate.

        attribute_stories = {}

        for tag in self.vars["alltags"]:
            for story in tag:
                attribute_stories[story.id] = story.needed_attributes()

        self.backend.write("ATTRIBUTES", attribute_stories)
        r = self.wait_response("ATTRIBUTES")
        self.attributes(r[1])

        # Short circuit for testing the above setup.
        if do_curses:
            log.debug("Starting curses.")
            self.screen = Screen()
            self.screen.init(self.backend.responses, callbacks)
            self.screen.refresh()

    def next_response(self, timeout=0):
        return self.backend.responses.get()

    def wait_response(self, cmd):
        log.debug("waiting on %s" % cmd)
        while True:
            r = self.next_response()
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

    def validate_config(self):
        self._val_bool("reader.show_description")
        self._val_bool("reader.enumerate_links")
        self._val_bool("story.enumerated")
        self._val_bool("taglist.tags_enumerated")
        self._val_bool("taglist.hide_empty_tags")
        self._val_bool("txt_browser")

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

    def attributes(self, d):
        for given_id in d:
            if not d[given_id]:
                # As of 08/08 this shouldn't happen ever.
                log.error("Caught item disappearing.")
                continue

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

    def var(self, args):
        t, r = self._first_term(args,\
                lambda : self.screen.input_callback("var: "))
        if t in self.vars:
            return (True, t, r)
        log.error("Unknown variable: %s" % t)
        return (False, None, None)

    @command_format("set", [("var","var")])
    @generic_parse_error
    def set(self, **kwargs):
        if self.vars[kwargs["var"]] in [ True, False]:
            self.set_var(kwargs["var"], True)
        else:
            log.error("Variable %s is not boolean." % kwargs["var"])

    @command_format("unset", [("var","var")])
    @generic_parse_error
    def unset(self, **kwargs):
        if self.vars[kwargs["var"]] in [True, False]:
            self.set_var(kwargs["var"], False)
        else:
            log.error("Variable %s is not boolean." % kwargs["var"])

    @command_format("toggle", [("var","var")])
    @generic_parse_error
    def toggle(self, **kwargs):
        var = kwargs["var"]
        self.set_var(var, not self.get_var(var))

    def set_var(self, tweak, value):
        changed = False
        if self.vars[tweak] != value:
            self.vars[tweak] = value
            changed = True

        # XXX use changed on vars needing refresh

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

    @command_format("toggle-opt", [("opt","opt")])
    @generic_parse_error
    def toggle_opt(self, **kwargs):
        opt = kwargs["opt"]
        if opt not in self.config:
            log.error("Unknown option: %s" % opt)
            return
        if type(self.config[opt]) != bool:
            log.error("Option %s isn't boolean." % opt)
            return
        self.set_opt(opt, not self.config[opt])

    def set_opt(self, option, value):
        changed = False
        if self.config[option] != value:
            self.config[option] = value
            changed = True

        # Special actions on certain opt changes.
        if changed:
            self.screen.refresh()
            self.backend.write("SETCONFIGS",\
                    { "CantoCurses." + option : unicode(value) })

    def get_opt(self, option):
        return self.config[option]

    def winch(self):
        self.backend.responses.put(("CMD", "resize"))

    def key(self, k):
        r = CommandHandler.key(self, k)
        if r:
            return r
        return self.screen.key(k)

    # Search for unescaped & to split up multiple commands.
    def cmd_split(self, cmd):
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

                cmds = self.cmd_split(cmd[1])

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
                elif cmd[1].startswith("set"):
                    self.set(args=cmd[1])
                elif cmd[1].startswith("unset"):
                    self.unset(args=cmd[1])
                elif cmd[1].startswith("toggle-opt"):
                    self.toggle_opt(args=cmd[1])
                elif cmd[1].startswith("toggle"):
                    self.toggle(args=cmd[1])

                # Propagate command to screen / subwindows
                elif cmd[1] != "noop":
                    self.screen.command(cmd[1])

            elif cmd[0] == "ATTRIBUTES":
                self.attributes(cmd[1])

            # XXX Server notification/reply

            if self.vars["needs_refresh"]:
                log.debug("Needed refresh")
                self.screen.refresh()
                self.vars["needs_refresh"] = False
                self.vars["needs_redraw"] = False
            elif self.vars["needs_redraw"]:
                log.debug("Needed redraw")
                self.screen.redraw()
                self.vars["needs_redraw"] = False

            if self.vars["needs_deferred_redraw"]:
                self.vars["needs_deferred_redraw"] = False
                self.vars["needs_redraw"] = True
