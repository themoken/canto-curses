# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

COMPATIBLE_VERSION = 0.2

from canto_next.hooks import call_hook, on_hook
from canto_next.plugins import Plugin

from command import CommandHandler, command_format
from html import html_entity_convert, char_ref_convert
from story import DEFAULT_FSTRING
from text import ErrorBox, InfoBox
from screen import Screen
from tag import Tag

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
            "protected_ids" : [],
            "transforms" : [],
            "taglist_visible_tags" : [],
        }

        self.callbacks = {
            "set_var" : self.set_var,
            "get_var" : self.get_var,
            "set_opt" : self.set_opt,
            "get_opt" : self.get_opt,
            "set_tag_opt" : self.set_tag_opt,
            "get_tag_opt" : self.get_tag_opt,
            "promote_tag" : self.promote_tag,
            "demote_tag" : self.demote_tag,
            "write" : self.backend.write
        }

        self.keys = {
            ":" : "command",
            "q" : "quit"
        }

        self.config = {
            "browser" : "firefox %u",
            "txt_browser" : False,
            "tags" : r"maintag\\:.*",
            "tagorder" : [],
            "update.auto.interval" : 60,
            "reader.maxwidth" : 0,
            "reader.maxheight" : 0,
            "reader.float" : True,
            "reader.align" : "topleft",
            "reader.border" : "smart",
            "reader.enumerate_links" : False,
            "reader.show_description" : True,
            "taglist.maxwidth" : 0,
            "taglist.maxheight" : 0,
            "taglist.float" : False,
            "taglist.align" : "neutral",
            "taglist.border" : "none",
            "taglist.tags_enumerated" : False,
            "taglist.tags_enumerated_absolute" : False,
            "taglist.hide_empty_tags" : True,
            "story.enumerated" : False,
            "story.format" : DEFAULT_FSTRING,
            "input.maxwidth" : 0,
            "input.maxheight" : 0,
            "input.float" : False,
            "input.align" : "bottom",
            "input.border" : "none",
            "errorbox.maxwidth" : 0,
            "errorbox.maxheight" : 0,
            "errorbox.float" : True,
            "errorbox.align" : "topleft",
            "errorbox.border" : "full",
            "infobox.maxwidth" : 0,
            "infobox.maxheight" : 0,
            "infobox.float" : True,
            "infobox.align" : "topleft",
            "infobox.border" : "full",

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
            "taglist.key.+" : "promote",
            "taglist.key.-" : "demote",

            "reader.key.space" : "destroy",
            "reader.key.d" : "toggle-opt reader.show_description",
            "reader.key.l" : "toggle-opt reader.enumerate_links",
            "reader.key.g" : "goto",
            "reader.key.down" : "scroll-down",
            "reader.key.up" : "scroll-up",
            "reader.key.npage" : "page-down",
            "reader.key.ppage" : "page-up",

            "errorbox.key.down" : "scroll-down",
            "errorbox.key.up" : "scroll-up",
            "errorbox.key.npage" : "page-down",
            "errorbox.key.ppage" : "page-up",
            "errorbox.key.space" : "destroy",

            "infobox.key.down" : "scroll-down",
            "infobox.key.up" : "scroll-up",
            "infobox.key.npage" : "page-down",
            "infobox.key.ppage" : "page-up",
            "infobox.key.space" : "destroy",

            "color.0" : curses.COLOR_WHITE,
            "color.1" : curses.COLOR_BLUE,
            "color.2" : curses.COLOR_YELLOW,
            "color.3" : curses.COLOR_BLUE,
            "color.4" : curses.COLOR_GREEN,
            "color.5" : curses.COLOR_MAGENTA,
            "color.6.fg" : curses.COLOR_WHITE,
            "color.6.bg" : curses.COLOR_RED,
        }

        self.tag_config = {}

        self.tag_template_config = {
            "enumerated" : False,
        }

        # Configuration options that, on change, require a refresh, in
        # regexen.

        self.refresh_configs = [re.compile(x) for x in\
                [ ".*enumerated", ".*hide_empty_tags",
                    ".*show_description", ".*enumerate_links" ]]

        self.tag_refresh_configs = [ re.compile(x) for x in\
                [ "enumerated" ]]

        # Configuration options that, on change, require an ncurses
        # reset or windows to be redone.

        self.winch_configs = [re.compile(x) for x in\
                [ "color\.*", ".*align", ".*float", ".*maxheight",
                    ".*maxwidth"]]

        self.tag_winch_configs = []

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
        self.prot_newtags(r[1])

        self.backend.write("WATCHCONFIGS", u"")
        self.backend.write("CONFIGS", [])
        self.prot_configs(self.wait_response("CONFIGS")[1])

        # Eval tags again, even though it's done in prot_newtags
        # because config options that were just parsed may effect
        # the order of tags.

        self.eval_tags()

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

    def _val_bool(self, config, defconfig, attr):
        if type(config[attr]) != bool:
            if config[attr].lower() == "true":
                config[attr] = True
            elif config[attr].lower() == "false":
                config[attr] = False
            else:
                config[attr] = def_config[attr]
                log.error("%s must be boolean. Resetting to %s" %
                        (attr, def_config[attr]))

    def _val_uint(self, config, defconfig, attr):
        if type(config[attr]) != int:
            try:
                config[attr] = int(config[attr])
            except:
                config[attr] = def_config[attr]
                log.error("%s must be integer. Resetting to %s" %
                        (attr, def_config[attr]))
        elif int < 0:
            config[attr] = config[attr]
            log.error("%s must be >= 0. Resetting to %s" %
                    (attr, config[attr]))

    def _val_color(self, config, defconfig, attr):
        if type(config[attr]) != int:
            try:
                config[attr] = int(config[attr])
            except:
                # Convert natural color into curses color #
                if config[attr] == "pink":
                    config[attr] == "magenta"
                for color_attr in dir(curses):
                    if color_attr.startswith("COLOR_") and\
                            config[attr] == color_attr[6:].lower():
                        config[attr] = getattr(curses, color_attr)
                        return

        # If we got an int from above, make sure it's ok.
        if type(config[attr]) == int:
            if -1 <= config[attr] <= 255:
                if config[attr] == -1 and not attr.endswith("bg"):
                    log.error("Only background elements can be -1.")
                else:
                    return

        # Couldn't parse, revert.
        if attr in self.def_config:
            log.error("Reverting %s to default: %s" %\
                    (attr, self.def_config[attr]))
            config[attr] = self.def_config[attr]
        else:
            del config[attr]

    # This isn't a validation per se, but it ensures that all tags
    # that we initially got are list in the order struct so we
    # can count on them being there.

    def _val_tag_order(self, config, defconfig, attr):
        try:
            config[attr] = eval(config[attr])
            log.debug("TO SET: %s" % config[attr])
        except:
            config[attr] = defconfig[attr]
            log.debug("TO DEFAULT: %s" % defconfig[attr])

        for tag in self.vars["alltags"]:
            if tag.tag not in config[attr]:
                config[attr].append(tag.tag)

    def validate_config(self, newconfig, defconfig):
        self._val_uint(newconfig, defconfig, "update.auto.interval")
        self._val_bool(newconfig, defconfig, "reader.show_description")
        self._val_bool(newconfig, defconfig, "reader.enumerate_links")
        self._val_bool(newconfig, defconfig, "story.enumerated")
        self._val_bool(newconfig, defconfig, "taglist.tags_enumerated")
        self._val_bool(newconfig, defconfig,\
                "taglist.tags_enumerated_absolute")
        self._val_bool(newconfig, defconfig, "taglist.hide_empty_tags")
        self._val_bool(newconfig, defconfig, "txt_browser")
        self._val_tag_order(newconfig, defconfig, "tagorder")

        # Make sure colors are all integers.
        for attr in [k for k in newconfig.keys() if k.startswith("color.")]:
            self._val_color(newconfig, defconfig, attr)

        # Make sure various window configurations make sense.
        for wintype in [ "reader", "input", "taglist" ]:
            # Ensure border attributes are sane:
            border_attr = wintype + ".border"
            if newconfig[border_attr] not in ["full","none","smart"]:
                log.error("Unknown border type for %s: %s" %\
                        (border_attr, newconfig[border_attr]))
                log.error("Reverting %s to %s" %\
                        (border_attr, defconfig[border_attr]))
                newconfig[border_attr] = defconfig[border_attr]

            # Ensure float attributes are boolean
            float_attr = wintype + ".float"
            self._val_bool(newconfig, defconfig, float_attr)

            # Ensure alignment jive with float.

            float_aligns = [ "topleft", "topright", "center", "neutral",\
                    "bottomleft", "bottomright"]

            tile_aligns = [ "top", "left", "bottom", "right", "neutral" ]

            align_attr = wintype + ".align"

            if newconfig[float_attr]:
                if newconfig[align_attr] not in float_aligns:

                    # Translate tile aligns to float aligns.
                    if newconfig[align_attr] in tile_aligns:
                        if newconfig[align_attr] in ["top","bottom"]:
                            newconfig[align_attr] += "left"
                        elif newconfig[align_attr] in ["left","right"]:
                            newconfig[align_attr] = "top" +\
                                    newconfig[align_attr]
                        log.info("Translated %s alignment for float: %s" %
                                (align_attr, newconfig[align_attr]))
                    else:
                        # Got nonsense, revert to default.
                        err = "%s unknown float alignment. Resetting to "
                        if defconfig[align_attr] not in float_aligns:
                            newconfig[float_attr] = False
                            err += "!float/"

                        newconfig[align_attr] = defconfig[align_attr]
                        err += defconfig[align_attr]
                        log.error(err % align_attr)
            # !floating
            else:
                # No translation since it would be ambiguous.
                if newconfig[align_attr] not in tile_aligns:
                    err = "%s unknown nonfloat alignment. Resetting to "
                    if defconfig[align_attr] in float_aligns:
                        newconfig[float_attr] = True
                        err += "float/"
                    newconfig[align_attr] = defconfig[align_attr]
                    err += defconfig[align_attr]
                    log.error(err % align_attr)

            # Make sure size restrictions are positive integers
            for subattr in [".maxheight", ".maxwidth"]:
                self._val_uint(newconfig, defconfig, wintype + subattr)

        return newconfig

    def validate_one_tag_config(self, config, defconfig):
        self._val_bool(config, defconfig, "enumerated")
        return config

    def validate_tag_config(self, config, defconfig):
        for k in config:
            onetagnew = config[k]
            onetagdef = defconfig[k]
            config[k] = self.validate_one_tag_config(onetagnew, onetagdef)

        return config

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

    def _dict_diff(self, d1, d2):
        changed_opts = []

        for k in d1:
            if k not in d2 or d2[k] != d1[k]:
                changed_opts.append(k)

        for k in d2:
            if k not in d1:
                changed_opts.append(k)

        return changed_opts

    def prot_configs(self, given):

        # If there are client config changes, validate them
        # and potentially queue up a redraw/refresh.

        if "CantoCurses" in given:
            new_config = self.config.copy()

            for k in given["CantoCurses"]:
                new_config[k] = given["CantoCurses"][k]

            # Need to validate to allow for content changes.
            new_config = self.validate_config(new_config, self.config)

            changed_opts = self._dict_diff(new_config, self.config)
            for opt in changed_opts:
                self.set_opt(opt, new_config[opt], 0)

        # Check for tag config changes.
        given_tag_config = {}
        for k in given.keys():
            if k.startswith("Tag "):
                given_tag_config[k] = given[k]

        # If no changes, we're done here.
        if not given_tag_config:
            return

        # Move over new tag configuration.
        new_config = self.tag_config.copy()
        for k in given_tag_config:
            new_config[k] = given_tag_config[k]

        new_config = self.validate_tag_config(new_config,
                self.tag_config)

        changed_opts = self._dict_diff(new_config, self.tag_config)
        for tag_header in changed_opts:
            tag = tag_header[4:]
            for cur_tag in self.vars["alltags"]:
                if curtag.tag == tag:
                    for k in changed_opts[tag_header]:
                        self.set_tag_opt(opt, tag, k,\
                                changed_opts[tag_header][k])
                    break

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
                if have_tag.tag == tag:
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
                        needed_attrs[id] = story.needed_attributes()

                    have_tag.remove_items(removes)
                    for id in removes:
                        unprotect["auto"].append(id)

        if needed_attrs:
            self.backend.write("ATTRIBUTES", needed_attrs)

        if unprotect:
            self.backend.write("UNPROTECT", unprotect)

    def prot_tagchange(self, tag):
        if tag not in self.updates:
            self.updates.append(tag)

    def prot_newtags(self, tags):
        for tag in tags:
            if tag not in [ t.tag for t in self.vars["alltags"] ]:
                log.info("Adding tag %s" % tag)
                Tag(tag, self.callbacks)

                # If we don't have configuration for this
                # tag already, substitute the default template.

                tagheading = "Tag %s" % tag
                if tagheading not in self.tag_config:
                    log.debug("Using default tag config for %s" % tag)
                    self.tag_config[tagheading] =\
                        self.tag_template_config.copy()
            else:
                log.warn("Got NEWTAG for already existing tag!")

            if tag not in self.config["tagorder"]:
                self.set_opt("tagorder", self.config["tagorder"] + [ tag ], 0)

        self.eval_tags()

    def prot_deltags(self, tags):
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

            if tag in self.config["tagorder"]:
                self.set_opt("tagorder",\
                        [ x for x in self.config["tagorder"] if x != tag ], 0)

        self.eval_tags()

    def prot_except(self, exception):
        self.set_var("error_msg", "%s" % exception)

    def prot_info(self, info):
        self.set_var("info_msg", "%s" % info)

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
        # We only care if the value is different, or it's a message
        # value, which should always cause a fresh message display,
        # even if it's the same error as before.

        if self.vars[tweak] != value or tweak in [ "error_msg", "info_msg"]:

            if tweak in [ "selected", "reader_item" ]:
                if self.vars[tweak]:
                    self.vars["protected_ids"].remove(self.vars[tweak].id)
                if value:
                    self.vars["protected_ids"].append(value.id)

            self.vars[tweak] = value

            if tweak in [ "error_msg" ] and self.screen:
                self.screen.add_window_callback(ErrorBox)
            elif tweak in [ "info_msg" ] and self.screen:
                self.screen.add_window_callback(InfoBox)

            call_hook("var_change", { tweak : value })

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

    def _check_opt_refresh(self, winch_configs, refresh_configs, changed_opts):
        if not self.screen:
            return

        should_winch = False
        for opt in changed_opts:
            for regx in winch_configs:
                if regx.match(opt):
                    should_winch = True

        # We only winch once. It would seem that WINCH would make the next loop
        # (refresh configs) moot and we should return.  However, if we block (as
        # on input), then the refresh will take place immediately while the
        # winch has to require queue action.

        if should_winch:
            self.winch()

        for opt in changed_opts:
            for regx in refresh_configs:
                if regx.match(opt):
                    self.screen.refresh()
                    return

    def check_opt_refresh(self, changed_opts):
        return self._check_opt_refresh(self.winch_configs,
                self.refresh_configs, changed_opts)

    def check_tag_opt_refresh(self, changed_opts):
        return self._check_opt_refresh(self.tag_winch_configs,
                self.tag_refresh_configs, changed_opts)

    # Any option changes must go through here, even ones we receive
    # from elsewhere, so we can call hooks.

    def set_opt(self, option, value, write=True):

        # XXX : Note that set_opt performs *no* validation and expects its
        # (internal) caller to have ensured that it's valid.

        if option not in self.config or self.config[option] != value:
            self.config[option] = value
            self.check_opt_refresh([option])

            call_hook("opt_change", [ { option : value } ])

            if write:
                self.backend.write("SETCONFIGS",\
                        { "CantoCurses" : { option : unicode(value) } })

    def get_opt(self, option):
        if option in self.config:
            return self.config[option]
        return None

    def set_tag_opt(self, tag, option, value):
        tagheader = "Tag %s" % tag.tag
        if option not in self.tag_config[tagheader] or\
                self.tag_config[tagheader][option] != value:
            self.tag_config[tagheader][option] = value
            self.check_tag_opt_refresh([option])
            call_hook("tag_opt_change", [ tag, { option : value }])
            self.backend.write("SETCONFIGS",\
                    { tagheader : { option : unicode(value) } } )

    def get_tag_opt(self, tag, option):
        tagheader = "Tag %s" % tag.tag
        if option in self.tag_config[tagheader]:
            return self.tag_config[tagheader][option]
        return None

    def promote_tag(self, tag, beforetag):
        tagorder = self.config["tagorder"][:]
        cur_idx = tagorder.index(tag.tag)
        before_idx = tagorder.index(beforetag.tag)

        if cur_idx <= before_idx:
            return

        tagorder.insert(before_idx - 1, tag.tag)
        tagorder.remove(tag.tag)
        tagorder.insert(before_idx, tag.tag)
        self.set_opt("tagorder", tagorder)
        self.eval_tags()

    def demote_tag(self, tag, aftertag):
        pass

    # This accepts arbitrary strings, but gives the right prompt.
    def transform(self, args):
        if not args:
            args = self.screen.input_callback("transform: ")
        return (True, args, None)

    # Setup a permanent, config based transform.
    @command_format([("transform","transform")])
    def cmd_transform(self, **kwargs):
        self.backend.write("SETCONFIGS",\
                    { "defaults" :
                        { "global_transform" : kwargs["transform"] }
                    })
        self._refresh()

    # Setup a temporary, per socket transform.
    @command_format([("transform","transform")])
    def cmd_temp_transform(self, **kwargs):
        self.backend.write("TRANSFORM", kwargs["transform"])
        self._refresh()

    @command_format([])
    def cmd_reconnect(self, **kwargs):
        self.backend.reconnect()

    def winch(self):
        self.winched = True

    def tick(self):
        self.ticked = True

    def do_tick(self):
        if self.update_interval <= 0:
            if self.updates:
                self.backend.write("ITEMS", self.updates)

            self.update_interval =\
                    self.config["update.auto.interval"]
            self.updates = []
        else:
            self.update_interval -= 1
        self.ticked = False

    @command_format([])
    def cmd_refresh(self, **kwargs):
        self._refresh()

    def _refresh(self):
        for tag in self.vars["curtags"]:
            tag.reset()
            self.backend.write("ITEMS", [ tag.tag ])

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

#    def run(self):
#        import cProfile
#        cProfile.runctx("self._run()", globals(), locals(), "canto-out")

    def run(self):
        # Priority commands / tuples allow a single user inputed string to
        # actually break down into multiple actions.

        priority = []

        while True:
            if self.ticked:
                self.ticked = False
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

            if self.vars["needs_redraw"]:
                log.debug("Needed redraw")
                self.screen.redraw()
                self.vars["needs_redraw"] = False

    def get_opt_name(self):
        return "main"
