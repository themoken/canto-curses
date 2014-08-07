# -*- coding: utf-8 -*-
#Canto-curses - ncurses RSS reader
#   Copyright (C) 2014 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

# This code provides two top level functions:
# parse_conditionals - which will return a list of strings and dicts that are
#    effectively a parse tree for all of the conditionals in the given format
#    string
#
# eval_theme_string - which will return the final, formatted string given their 
#    associated values.

# NOTE: This code guarantees that any given conditional expression or other
# eval()'d string will be evaluated exactly once. This means that it's
# impossible to cause the code to infinitely recurse with a value like
# { 'a' : '%a' }.

from .html import html_entity_convert, char_ref_convert

import traceback
import logging
import re

log = logging.getLogger("PARSER")

# Break the first conditional out of a string
# For example two top level ternaries: 
#   "Prefix %?{a}(true : false) %?{b}(trueb : falseb)"
# Will return
#   ['Prefix', { 'a' : { True : ["true"], False : ["false"] }}, ' %?{b}(trueb : falseb)']
# ( Note the second b ternary hasn't been split out )

tern_start = re.compile("(.*?[^\\\\]?)%\\?{([^}]*)}\\(")

def _parse_one_conditional(uni):
    strings = []

    m = tern_start.match(uni)

    # No ternaries detected.
    if not m:
        return [ uni ]

    # Append the potential prefix.
    strings.append(m.group(1))

    code = m.group(2)
    # Add the relevant escape
    strings.append({ code : {}})

    escaped = False
    paren = 1
    value = ""

    for i, c in enumerate(uni[m.end():]):
        if escaped:
            value += c
            escaped = False
        elif c == "\\":
            escaped = True
        elif c == "(":
            paren += 1
            value += c
        elif c == ":" and paren == 1:
            strings[-1][code][True] = value
            value = ""
        elif c == ")":
            paren -= 1

            # This is the closing paren
            if paren == 0:
                strings[-1][code][False] = value

                # Append the rest of the string.
                value = uni[i + m.end() + 1:]
                if value:
                    strings.append(value)
                    break

            # Not the right paren, include it.
            else:
                value += c

        # Normal character, include it.
        else:
            value += c

    return strings

# Like the above, except recurse to find the final
# representation of the string.

def parse_conditionals(uni):
    strings = _parse_one_conditional(uni)

    # If there were no conditionals,
    # no need to continue.
    if len(strings) == 1:
        return strings

    # Otherwise, check the resulting strings
    # for ternaries.

    ret_strings = []

    for term in strings:
        if type(term) == dict:

            # For now, toplevel dicts will have only one
            # key, and I can't see a reason to expand it
            # but let's iterate anyway.

            for topkey in term:
                for subkey in term[topkey]:
                    term[topkey][subkey] =\
                            parse_conditionals(term[topkey][subkey])
            ret_strings.append(term)
        else:
            ret_strings += parse_conditionals(term)

    return ret_strings

# This function evaluates a simple string, detecting any
# python eval sequences.

def _eval_simple(uni, values):
    r = ""
    escaped = False

    in_code = False
    long_code = False
    code = ""

    for c in uni:
        if escaped:
            if in_code:
                code += c
            else:
                r += c
            escaped = False
        elif c == '\\':
            escaped = True

        elif c == '}' and in_code and long_code:
            r += str(eval(code, {}, values))
            code = ""
            in_code = False
            long_code = False
        elif c == '{' and in_code and code == "":
            long_code = True
        elif in_code:
            if long_code:
                code += c
            elif c in values:
                r += str(values[c])
                in_code = False
            else:
                Exception("Unknown escape: %s" % c)
                in_code = False
        elif c == '%':
            in_code = True
        else:
            r += c

    return r

def eval_theme_string(parsed, values):
    r = ""
    for term in parsed:
        if type(term) == dict:

            # Once again, iterate even though the top level dicts only have
            # a single key. This will cause trouble if there are multiple
            # keys however, as the order is varied.

            for topkey in term:
                val = eval(topkey, {}, values)
                if val:
                    r += eval_theme_string(term[topkey][True], values)
                else:
                    r += eval_theme_string(term[topkey][False], values)
        else:
            r += _eval_simple(term, values)
    return r

def prep_for_display(s):
    s = s.replace("\\", "\\\\")
    s = s.replace("%", "\\%")
    s = html_entity_convert(s)
    s = char_ref_convert(s)
    return s
