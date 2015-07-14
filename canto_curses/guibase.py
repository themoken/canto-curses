# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto_next.hooks import on_hook
from canto_next.plugins import Plugin
from canto_next.remote import assign_to_dict, access_dict

from .command import CommandHandler, register_commands, register_arg_types, unregister_all, _string, register_aliases, commands, command_help, groups
from .tagcore import tag_updater
from .theme import prep_for_display
from .config import needs_eval, config

import logging

log = logging.getLogger("COMMON")

import subprocess
import tempfile
import urllib.request, urllib.error, urllib.parse
import shlex
import sys

import os
import os.path

class BasePlugin(Plugin):
    pass

class GuiBase(CommandHandler):
    def init(self):
        args = {
            "key": ("[key]: Simple keys (a), basic chords (C-r, M-a), or named whitespace like space or tab", _string),
            "command": ("[command]: Any canto-curses command. (Will show current binding if not given)\n  Simple: goto\n  Chained: foritems \\\\& goto \\\\& item-state read \\\\& clearitems \\\\& next-item", self.type_unescape_command),
            "remote-cmd": ("[remote cmd]", self.type_remote_cmd),
            "url" : ("[URL]", _string),
            "help-command" : ("[help-command]: Any canto-curses command, if blank, 'any' or unknown, will display help overview", self.type_help_cmd),
            "config-option" : ("[config-option]: Any canto-curses option", self.type_config_option),
            "config-section" : ("[config-section]: A canto-curses config section", self.type_config_section),
            "executable" : ("[executable]: A program in your PATH", self.type_executable),
        }

        cmds = {
            "bind" : (self.cmd_bind, [ "key", "command" ], "Add or query %s keybinds" % self.get_opt_name()),
            "transform" : (self.cmd_transform, ["string"], "Set user transform"),
            "remote addfeed" : (lambda x : self.cmd_remote("addfeed", x), ["url"], "Subscribe to a feed"),
            "remote listfeeds" : (lambda : self.cmd_remote("listfeeds", ""), [], "List feeds"),
            "remote": (self.cmd_remote, ["remote-cmd", "string"], "Give a command to canto-remote"),
            "destroy": (self.cmd_destroy, [], "Destroy this %s" % self.get_opt_name()),
            "set" : (self.cmd_set, ["config-option", "string"],

"""Set configuration options

Common options:
    %BSetting browser options%b

    :set browser.path /path/to/browser
    :set browser.text [True|False]
        - True: text browser like elinks
        * False: graphical browser like Firefox

    %BSetting update styles%b

    :set update.style [maintain|append|prepend]
        - maintain: re-sort items into feed
        * append: add new items to the end of feeds
        - prepend: add new items to the top of feeds

    :set update.auto.interval <seconds>
    :set update.auto.enabled [True|False]
        - True: interface will automatically add new items
        * False: new items have to be requested with :update (\\\ by default)

    %BChanging feed defaults%b

    :set defaults.keep_time <seconds>
        - How long items are kept after they disappear from source data
    :set defaults.keep_unread [True|False]
        - True: unread items will be keep forever
        * False: unread items will be discarded if old enough

    %BChanging a setting per-feed (with item selected)%b

    :set feed.keep_time
    :set feed.keep_unread

    %BChanging filters/sorts%b

    :set defaults.global_transform <transform>
        - Basic transforms
            - None (see all items all the time)
            * filter_read (filter out read items)

    :set tag.transform <transform>
"""),
            "set browser.path" : (lambda x : self.cmd_set("browser.path", x), ["executable"], "Set desired browser"),
            "reset-config" : (self.cmd_reset_config, [ "config-section" ], "Reset canto-curses config (won't touch daemon / feed settings)")
        }

        help_cmds = {
            "help" : (self.cmd_help, ["help-command"], "Get help on a specific command")
        }

        aliases = {
            "add" : "remote addfeed",
            "del" : "remote delfeed",
            "list" : "remote listfeeds",

            # Compatibility / evaluation aliases
            "set global_transform" : "set defaults.global_transform",
            "set keep_time" : "set defaults.keep_time",
            "set keep_unread" : "set defaults.keep_unread",
            "set browser " : "set browser.path ",
            "set txt_browser " : "set browser.text ",
            "set update.auto " : "set update.auto.enabled ",
            "set border" : "set taglist.border",

            "filter" : "transform",
            "sort" : "transform",

            "next-item" : "rel-set-cursor 1",
            "prev-item" : "rel-set-cursor -1",
        }

        register_arg_types(self, args)

        register_commands(self, cmds, "Base")
        register_commands(self, help_cmds, "Help")

        register_aliases(self, aliases)

        self.editor = None

        self.plugin_class = BasePlugin
        self.update_plugin_lookups()

    def cmd_destroy(self):
        self.callbacks["die"](self)

    def die(self):
        unregister_all(self)

    # Provide completions, but we don't care to verify settings.

    def type_executable(self):
        executables = []
        for path_dir in os.environ["PATH"].split(os.pathsep):
            try:
                for f in os.listdir(path_dir):
                    fullpath = os.path.join(path_dir, f)
                    if os.path.isfile(fullpath) and os.access(fullpath, os.X_OK):
                        executables.append(f)

            # PATH directories aren't guaranteed to exist and a myriad of other
            # errors should just silently move on. Worst case is incomplete
            # list of completions.

            except:
                pass

        return (executables, lambda x : (True, x))

    def _fork(self, path, href, text):
        pid = os.fork()

        # Parents can now bail.
        if pid:
            return pid

        # Make sure that we quote href such that malicious URLs like
        # "http://example.com & rm -rf ~/" won't be interpreted by the shell.

        href = shlex.quote(href)

        # A lot of programs don't appreciate
        # having their fds closed, so instead
        # we dup them to /dev/null.

        fd = os.open("/dev/null", os.O_RDWR)
        os.dup2(fd, sys.stderr.fileno())

        if not text:
            os.setpgid(os.getpid(), os.getpid())
            os.dup2(fd, sys.stdout.fileno())
            os.dup2(fd, sys.stdin.fileno())

        if "%u" in path:
            path = path.replace("%u", href)
        elif href:
            path = path + " " + href

        os.execv("/bin/sh", ["/bin/sh", "-c", path])

        # Just in case.
        sys.exit(0)

    def type_remote_cmd(self):
        remote_cmds = [ "help", "addfeed", "listfeeds", "delfeed",
                "force-update", "config", "one-config", "export",
                "import", "kill" ]
        return (remote_cmds, lambda x : (True, x))

    def _remote_argv(self, argv):
        loc_args = self.callbacks["get_var"]("location")
        argv = [argv[0]] + loc_args + argv[1:]

        log.debug("Calling remote: %s", argv)

        # check_output return bytes, we must decode.
        out = subprocess.check_output(argv).decode()

        if out:
            log.debug("Output:")
            log.debug(out.rstrip())

            # Strip anything that could be misconstrued as style
            # from remote output.

            out = out.replace("%","\\%")

            log.info(out.rstrip())

    def _remote(self, args):
        args = "canto-remote " + args

        # Add location args, so the remote is connecting
        # to the correct daemon.

        self._remote_argv(shlex.split(args))

    def remote_args(self, args):
        return self.string(args, "remote: ")

    def cmd_remote(self, remote_cmd, args):
        self._remote("%s %s" % (remote_cmd, args))

    def _goto(self, urls):
        browser = self.callbacks["get_conf"]()["browser"]

        if not browser["path"]:
            log.error("No browser defined! Cannot goto.")
            return

        if browser["text"]:
            self.callbacks["pause_interface"]()

        for url in urls:
            pid = self._fork(browser["path"], url, browser["text"])
            if browser["text"]:
                os.waitpid(pid, 0)

        if browser["text"]:
            self.callbacks["unpause_interface"]()

    def cmd_transform(self, transform):
        tag_updater.transform("user", transform)
        tag_updater.reset(True)
        tag_updater.update()

    def type_unescape_command(self):
        def validate_uescape_command(x):
            # Change the escaped '&' from shlex into a raw &
            return (True, x.replace(" '&' ", " & "))
        return (None, validate_uescape_command)

    def cmd_bind(self, key, cmd):
        self.bind(key, cmd.lstrip().rstrip(), True)

    def bind(self, key, cmd, overwrite=False):
        opt = self.get_opt_name()
        key = self.translate_key(key)
        c = self.callbacks["get_conf"]()
        if not cmd:
            if key in c[opt]["key"]:
                log.info("[%s] %s = %s" % (opt, key, c[opt]["key"][key]))
                return True
            else:
                return False
        else:
            if key in c[opt]["key"] and c[opt]["key"][key] and not overwrite:
                log.debug("%s already bound to %s", key, c[opt]["key"][key])
                return False

            log.debug("Binding %s.%s to %s", opt, key, cmd)

            c[opt]["key"][key] = cmd
            self.callbacks["set_conf"](c)
            return True

    def type_help_cmd(self):
        help_cmds = commands()

        def help_validator(x):
            if x in ["commands", "cmds"]:
                return (True, 'commands')
            if x in help_cmds:
                return (True, x)
            return (True, 'all')

        return (help_cmds, help_validator)

    def cmd_help(self, cmd):
        if self.callbacks["get_var"]("info_msg"):
            self.callbacks["set_var"]("info_msg", "")

        if cmd == 'all':
            log.info("%BHELP%b\n")
            log.info("This is a list of available keybinds.\n")
            log.info("For a list of commands, type ':help commands'\n")
            log.info("For help with a specific command, type ':help [command]'\n")
            log.info("%BBinds%b")

            config = self.callbacks["get_conf"]()

            for optname in [ "main", "infobox", "taglist", "reader" ]:
                if "key" in config[optname] and list(config[optname]["key"].keys()) != []:
                    maxbindl = max([ len(x) for x in config[optname]["key"].keys() ]) + 1
                    log.info("\n%B" + optname.title() + "%b\n")
                    for bind in sorted(config[optname]["key"]):
                        bindeff = prep_for_display(bind + (" " * (maxbindl - len(bind))))
                        cmd = prep_for_display(config[optname]["key"][bind])
                        log.info("%s %s" % (bindeff, cmd))

        elif cmd == 'commands':
            for group in sorted(groups()):
                log.info("%B" + group + "%b\n")
                tmp = {}
                for c in commands(group):
                    tmp[c] = command_help(c)

                maxcmdl = max([ len(x) for x in tmp ])
                for c in sorted(tmp.keys()):
                    ceff = c + (" " * (maxcmdl - len(c)))
                    log.info("%s - %s" % (ceff, tmp[c]))
                log.info("")
        else:
            log.info(command_help(cmd, True))

    # Validate a single config option
    # Will offer completions for any recognized config option
    # Will *not* reject validly formatted options that don't already exist

    def _get_current_config_options(self, obj, stack):
        r = []

        for item in obj.keys():
            stack.append(item)

            if type(obj[item]) == dict:
                r.extend(self._get_current_config_options(obj[item], stack[:]))
            else:
                r.append(shlex.quote(".".join(stack)))

            stack = stack[:-1]

        return r

    def type_config_option(self):
        conf = self.callbacks["get_conf"]()

        possibles = self._get_current_config_options(conf, [])
        possibles.extend(self._get_current_config_options(config.daemon_defaults, ["defaults"]))
        possibles.extend(self._get_current_config_options(config.tag_template_config, ["tag"]))
        possibles.extend(self._get_current_config_options({ "rate" : 10, "keep_time" : 86400, "keep_unread" : False}, ["feed"]))
        possibles.sort()

        return (possibles, lambda x : (True, x))

    def type_config_section(self):
        conf = self.callbacks["get_conf"]()
        possibles = [ "" ] + list(conf.keys())
        return (possibles, lambda x : (x in possibles, x))

    def cmd_set(self, opt, val):
        log.debug("SET: %s '%s'", opt, val)

        evaluate = needs_eval(opt)

        if val != "" and evaluate:
            log.debug("Evaluating...")
            try:
                val = eval(val)
            except Exception as e:
                log.error("Couldn't eval '%s': %s" % (val, e))
                return

        if opt.startswith("defaults."):
            conf = { "defaults" : self.callbacks["get_defaults"]() }

            if val != "":
                assign_to_dict(conf, opt, val)
                self.callbacks["set_defaults"](conf["defaults"])
        elif opt.startswith("feed."):
            sel = self.callbacks["get_var"]("selected")
            if not sel:
                log.info("Feed settings only work with a selected item")
                return

            if sel.is_tag:
                try_tag = sel
            else:
                try_tag = sel.parent_tag

            if not try_tag.tag.startswith("maintag:"):
                log.info("Selection is in a user tag, cannot set feed settings")
                return

            name = try_tag.tag[8:]

            conf = { "feed" : self.callbacks["get_feed_conf"](name) }

            if val != "":
                assign_to_dict(conf, opt, val)
                self.callbacks["set_feed_conf"](name, conf["feed"])
        elif opt.startswith("tag."):
            sel = self.callbacks["get_var"]("selected")
            if not sel:
                log.info("Tag settings only work with a selected item")
                return

            if sel.is_tag:
                tag = sel
            else:
                tag = sel.parent_tag

            conf = { "tag" : self.callbacks["get_tag_conf"](tag.tag) }

            if val != "":
                assign_to_dict(conf, opt, val)
                self.callbacks["set_tag_conf"](tag.tag, conf["tag"])
        else:
            conf = self.callbacks["get_conf"]()

            if val != "":
                assign_to_dict(conf, opt, val)
                self.callbacks["set_conf"](conf)

        ok, val = access_dict(conf, opt)
        if not ok:
            log.error("Unknown option %s" % opt)
            log.error("Full conf: %s" % conf)
        else:
            log.info("%s = %s" % (opt, val))

    def cmd_reset_config(self, option):
        if option == "":
            log.info("Resetting to defaults")
            self.callbacks["set_conf"](config.template_config)
        else:
            log.info("Resetting %s to defaults", option)
            conf = self.callbacks["get_conf"]()
            conf[option] = config.template_config[option]
            self.callbacks["set_conf"](conf)
