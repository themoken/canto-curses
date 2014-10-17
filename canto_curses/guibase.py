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

from .command import CommandHandler, register_commands, register_arg_types, unregister_all, _string, register_aliases, commands, command_help
from .tagcore import tag_updater
from .parser import prep_for_display
from .config import needs_eval

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
            "executable" : ("[executable]: A program in your PATH", self.type_executable),
        }

        cmds = {
            "bind" : (self.cmd_bind, [ "key", "command" ], "Add or query %s keybinds" % self.get_opt_name()),
            "transform" : (self.cmd_transform, ["string"], "Set user transform"),
            "remote addfeed" : (lambda x : self.cmd_remote("addfeed", x), ["url"], "Subscribe to a feed"),
            "remote listfeeds" : (lambda : self.cmd_remote("listfeeds", ""), [], "List feeds"),
            "remote": (self.cmd_remote, ["remote-cmd", "string"], "Give a command to canto-remote"),
            "destroy": (self.cmd_destroy, [], "Destroy this %s" % self.get_opt_name()),
            "set" : (self.cmd_set, ["config-option", "string"], "Set configuration options"),
            "set browser.path" : (lambda x : self.cmd_set("browser.path", x), ["executable"], "Set desired browser"),
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
            for f in os.listdir(path_dir):
                fullpath = os.path.join(path_dir, f)
                if os.path.isfile(fullpath) and os.access(fullpath, os.X_OK):
                    executables.append(f)

        return (executables, lambda x : (True, x))

    def _fork(self, path, href, text, fetch=False):

        # Prepare temporary files, if fetch.

        if fetch:
            # Get a path (sans query strings, etc.) for the URL
            tmppath = urllib.parse.urlparse(href).path

            # Return just the basename of the path (no directories)
            fname = os.path.basename(tmppath)

            # Grab a temporary directory. This allows us to create a file with
            # an unperturbed filename so scripts can freely use regex /
            # extension matching in addition to mimetype detection.

            tmpdir = tempfile.mkdtemp(prefix="canto-")
            tmpnam = tmpdir + '/' + fname

            on_hook("curses_exit", lambda : (os.unlink(tmpnam)))
            on_hook("curses_exit", lambda : (os.rmdir(tmpdir)))

        pid = os.fork()

        # Parents can now bail.
        if pid:
            return pid

        if fetch:
            tmp = open(tmpnam, 'w+b')

            # Grab the HTTP info / prepare to read.
            response = urllib.request.urlopen(href)

            # Grab in kilobyte chunks to avoid wasting memory on something
            # that's going to be immediately written to disk.

            while True:
                r = response.read(1024)
                if not r:
                    break
                tmp.write(r)

            response.close()
            tmp.close()

            href = tmpnam

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

        if "%u" in path:
            path = path.replace("%u", href)
        elif href:
            path = path + " " + href

        os.execv("/bin/sh", ["/bin/sh", "-c", path])

        # Just in case.
        sys.exit(0)

    def _edit(self, text):
        if not self.editor:
            self.editor = os.getenv("EDITOR")
        if not self.editor:
            self.editor = self.input("editor: ")

        # No editor, or cancelled dialog, no change.
        if not self.editor:
            return text

        self.callbacks["pause_interface"]()

        # Setup tempfile to edit.
        fd, path = tempfile.mkstemp(text=True)

        f = os.fdopen(fd, "w")
        f.write(text)
        f.close()

        # Invoke editor
        logging.info("Invoking editor on %s" % path)
        pid = self._fork(self.editor + " %u", path, True)
        pid, status = os.waitpid(pid, 0)

        if status == 0:
            f = open(path, "r")
            r = f.read()
            f.close()
        else:
            self.callbacks["set_var"]("error_msg",
                    "Editor failed! Status = %d" % (status,))
            r = text

        # Cleanup temp file.
        os.unlink(path)

        self.callbacks["unpause_interface"]()

        return r

    def cmd_edit(self, **kwargs):
        t = self.callbacks["get_opt"](kwargs["opt"])
        r = self._edit(t)
        log.info("Edited %s to %s" % (kwargs["opt"], r))
        self.callbacks["set_opt"](kwargs["opt"], r)

    def type_remote_cmd(self):
        remote_cmds = [ "help", "addfeed", "listfeeds", "delfeed",
                "force-update", "config", "one-config", "export",
                "import", "kill" ]
        return (remote_cmds, lambda x : (x in remote_cmds, x))

    def _remote_argv(self, argv):
        loc_args = self.callbacks["get_var"]("location")
        argv = [argv[0]] + loc_args + argv[1:]

        log.debug("Calling remote: %s" % argv)

        # check_output return bytes, we must decode.
        out = subprocess.check_output(argv).decode()

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

    def _goto(self, urls, fetch=False):
        browser = self.callbacks["get_conf"]()["browser"]

        if not browser["path"]:
            log.error("No browser defined! Cannot goto.")
            return

        if browser["text"]:
            self.callbacks["pause_interface"]()

        for url in urls:
            pid = self._fork(browser["path"], url, browser["text"], fetch)
            if browser["text"]:
                os.waitpid(pid, 0)

        if browser["text"]:
            self.callbacks["unpause_interface"]()

    # Like goto, except download the file to /tmp before executing browser.

    def _fetch(self, urls):
        self._goto(urls, True)

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
                log.debug("%s already bound to %s" % (key, c[opt]["key"][key]))
                return False

            log.debug("Binding %s.%s to %s" % (opt, key, cmd))

            c[opt]["key"][key] = cmd
            self.callbacks["set_conf"](c)
            return True

    def type_help_cmd(self):
        help_cmds = commands()

        def help_validator(x):
            if x in ["commands", "cmds"]:
                return (True, 'commands')
            for group in help_cmds:
                if x in help_cmds[group]:
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

            for optname in [ "main", "taglist", "reader" ]:
                if "key" in config[optname] and list(config[optname]["key"].keys()) != []:
                    maxbindl = max([ len(x) for x in config[optname]["key"].keys() ]) + 1
                    log.info("\n%B" + optname + "%b\n")
                    for bind in sorted(config[optname]["key"]):
                        bindeff = prep_for_display(bind + (" " * (maxbindl - len(bind))))
                        cmd = prep_for_display(config[optname]["key"][bind])
                        log.info("%s %s" % (bindeff, cmd))

        elif cmd == 'commands':
            gc = commands()
            for group in sorted(gc.keys()):
                log.info("%B" + group + "%b\n")
                for c in sorted(gc[group]):
                    log.info(command_help(c))
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
        possibles.sort()

        return (possibles, lambda x : (True, x))

    def cmd_set(self, opt, val):
        log.debug("SET: %s '%s'" % (opt, val))

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
