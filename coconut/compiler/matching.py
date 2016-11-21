#!/usr/bin/env python
# -*- coding: utf-8 -*-

#-----------------------------------------------------------------------------------------------------------------------
# INFO:
#-----------------------------------------------------------------------------------------------------------------------

"""
Author: Evan Hubinger
License: Apache 2.0
Description: Handles Coconut pattern-matching.
"""

#-----------------------------------------------------------------------------------------------------------------------
# IMPORTS:
#-----------------------------------------------------------------------------------------------------------------------

from __future__ import print_function, absolute_import, unicode_literals, division

from coconut.root import *  # NOQA

from contextlib import contextmanager

from coconut.exceptions import (
    CoconutInternalException,
    CoconutDeferredSyntaxError,
)
from coconut.constants import (
    match_temp_var,
    wildcard,
    openindent,
    closeindent,
    match_check_var,
    const_vars,
)

#-----------------------------------------------------------------------------------------------------------------------
# UTILITIES:
#-----------------------------------------------------------------------------------------------------------------------


def get_match_names(match):
    """Gets keyword names for the given match."""
    names = []
    if "paren" in match.keys():
        (match,) = match
        names += get_match_names(match)
    elif "var" in match.keys():
        (setvar,) = match
        if setvar != wildcard:
            names.append(setvar)
    elif "trailer" in match.keys():
        match, trailers = match[0], match[1:]
        for i in range(0, len(trailers), 2):
            op, arg = trailers[i], trailers[i + 1]
            if op == "as":
                names.append(arg)
        names += get_match_names(match)
    return names

#-----------------------------------------------------------------------------------------------------------------------
# MATCHER:
#-----------------------------------------------------------------------------------------------------------------------


class Matcher(object):
    """Pattern-matching processor."""
    matchers = {
        "dict": lambda self: self.match_dict,
        "iter": lambda self: self.match_iterator,
        "series": lambda self: self.match_sequence,
        "rseries": lambda self: self.match_rsequence,
        "mseries": lambda self: self.match_msequence,
        "const": lambda self: self.match_const,
        "var": lambda self: self.match_var,
        "set": lambda self: self.match_set,
        "data": lambda self: self.match_data,
        "paren": lambda self: self.match_paren,
        "trailer": lambda self: self.match_trailer,
        "and": lambda self: self.match_and,
        "or": lambda self: self.match_or,
        "star": lambda self: self.match_star,
    }
    __slots__ = (
        "position",
        "var_index",
        "checkdefs",
        "checks",
        "defs",
        "names",
        "others"
    )

    def __init__(self, checkdefs=None, names=None, var_index=0):
        """Creates the matcher."""
        self.position = 0
        self.var_index = var_index
        self.checkdefs = []
        if checkdefs is None:
            self.increment()
        else:
            for checks, defs in checkdefs:
                self.checkdefs.append([checks[:], defs[:]])
            self.checks = self.get_checks(-1)
            self.defs = self.get_defs(-1)
        self.names = {} if names is None else names
        self.others = []

    def duplicate(self):
        """Duplicates the matcher to others."""
        self.others.append(Matcher(self.checkdefs, self.names, self.var_index))
        self.others[-1].set_checks(0, ["not " + match_check_var] + self.others[-1].get_checks(0))
        return self.others[-1]

    def get_checks(self, position):
        """Gets the checks at the position."""
        return self.checkdefs[position][0]

    def set_checks(self, position, checks):
        """Sets the checks at the position."""
        self.checkdefs[position][0] = checks

    def set_defs(self, position, defs):
        """Sets the defs at the position."""
        self.checkdefs[position][1] = defs

    def get_defs(self, position):
        """Gets the defs at the position."""
        return self.checkdefs[position][1]

    @contextmanager
    def only_self(self):
        """Only match in self not others."""
        others, self.others = self.others, []
        try:
            yield
        finally:
            self.others = others + self.others

    def add_check(self, check_item):
        """Adds a check universally."""
        self.checks.append(check_item)
        for other in self.others:
            other.add_check(check_item)

    def add_def(self, def_item):
        """Adds a def universally."""
        self.defs.append(def_item)
        for other in self.others:
            other.add_def(def_item)

    def set_position(self, position):
        """Sets the if-statement position."""
        if position > 0:
            while position >= len(self.checkdefs):
                self.checkdefs.append([[], []])
            self.checks = self.checkdefs[position][0]
            self.defs = self.checkdefs[position][1]
            self.position = position
        else:
            raise CoconutInternalException("invalid match index", position)

    @contextmanager
    def incremented(self, forall=False):
        """Increment then decrement."""
        self.increment(forall)
        try:
            yield
        finally:
            self.decrement(forall)

    def increment(self, forall=False):
        """Advances the if-statement position."""
        self.set_position(self.position + 1)
        if forall:
            for other in self.others:
                other.increment(True)

    def decrement(self, forall=False):
        """Decrements the if-statement position."""
        self.set_position(self.position - 1)
        if forall:
            for other in self.others:
                other.decrement(True)

    def add_guard(self, cond):
        """Adds cond as a guard."""
        self.increment(True)
        self.add_check(cond)

    def get_temp_var(self):
        """Gets the next match_temp_var."""
        tempvar = match_temp_var + "_" + str(self.var_index)
        self.var_index += 1
        return tempvar

    def match_all_in(self, matches, item):
        """Matches all matches to elements of item."""
        for x in range(len(matches)):
            self.match(matches[x], item + "[" + str(x) + "]")

    def check_len_in(self, min_len, max_len, item):
        """Checks that the length of item is in range(min_len, max_len+1)."""
        if max_len is None:
            if min_len:
                self.add_check("_coconut.len(" + item + ") >= " + str(min_len))
        elif min_len == max_len:
            self.add_check("_coconut.len(" + item + ") == " + str(min_len))
        elif not min_len:
            self.add_check("_coconut.len(" + item + ") <= " + str(max_len))
        else:
            self.add_check(str(min_len) + " <= _coconut.len(" + item + ") <= " + str(max_len))

    def match_function(self, args, kwargs, match_args=[], star_arg=None, kwd_args=[], dubstar_arg=None):
        """Matches a pattern-matching function."""
        self.match_in_args_kwargs(match_args, args, kwargs, allow_star_args=star_arg is not None)
        if star_arg is not None:
            self.match(star_arg, args + "[" + str(len(match_args)) + ":]")
        self.match_in_kwargs(kwd_args, kwargs)
        if dubstar_arg is None:
            with self.incremented():
                self.add_check("not " + kwargs)
        else:
            self.add_def(dubstar_arg + " = " + kwargs)

    def match_in_args_kwargs(self, match_args, args, kwargs, allow_star_args=False):
        """Matches against args or kwargs."""
        req_len = 0
        arg_checks = {}
        for x in range(len(match_args)):
            if isinstance(match_args[x], tuple):
                (match, default) = match_args[x]
            else:
                match, default = match_args[x], None
            names = get_match_names(match)
            if default is None:
                if not names:
                    self.match(match, args + "[" + str(x) + "]")
                    req_len = x + 1
                else:
                    arg_checks[x] = (
                        # if x < req_len
                        " and ".join('"' + name + '" not in ' + kwargs for name in names),
                        # if x >= req_len
                        "_coconut.sum((_coconut.len(" + args + ") > " + str(x) + ", "
                        + ", ".join('"' + name + '" in ' + kwargs for name in names)
                        + ")) == 1",
                    )
                    tempvar = self.get_temp_var()
                    self.add_def(tempvar + " = "
                                 + args + "[" + str(x) + "] if _coconut.len(" + args + ") > " + str(x) + " else "
                                 + "".join(kwargs + '.pop("' + name + '") if "' + name + '" in ' + kwargs + " else "
                                           for name in names[:-1])
                                 + kwargs + '.pop("' + names[-1] + '")'
                                 )
                    with self.incremented():
                        self.match(match, tempvar)
            else:
                if not names:
                    tempvar = self.get_temp_var()
                    self.add_def(tempvar + " = " + args + "[" + str(x) + "] if _coconut.len(" + args + ") > " + str(x) + " else " + default)
                    with self.increment():
                        self.match(match, tempvar)
                else:
                    arg_checks[x] = (
                        # if x < req_len
                        None,
                        # if x >= req_len
                        "_coconut.sum((_coconut.len(" + args + ") > " + str(x) + ", "
                        + ", ".join('"' + name + '" in ' + kwargs for name in names)
                        + ")) <= 1",
                    )
                    tempvar = self.get_temp_var()
                    self.add_def(tempvar + " = "
                                 + args + "[" + str(x) + "] if _coconut.len(" + args + ") > " + str(x) + " else "
                                 + "".join(kwargs + '.pop("' + name + '") if "' + name + '" in ' + kwargs + " else "
                                           for name in names)
                                 + default
                                 )
                    with self.incremented():
                        self.match(match, tempvar)

        max_len = None if allow_star_args else len(match_args)
        self.check_len_in(req_len, max_len, args)
        for x in arg_checks:
            if x < req_len:
                if arg_checks[x][0] is not None:
                    self.add_check(arg_checks[x][0])
            else:
                if arg_checks[x][1] is not None:
                    self.add_check(arg_checks[x][1])

    def match_in_kwargs(self, match_args, kwargs):
        """Matches against kwargs."""
        for match, default in match_args:
            names = get_match_names(match)
            if names:
                tempvar = self.get_temp_var()
                self.add_def(tempvar + " = "
                             + "".join(kwargs + '.pop("' + name + '") if "' + name + '" in ' + kwargs + " else "
                                       for name in names)
                             + default
                             )
                with self.incremented():
                    self.match(match, tempvar)
            else:
                raise CoconutDeferredSyntaxError("keyword-only pattern-matching function arguments must have names")

    def match_dict(self, tokens, item):
        """Matches a dictionary."""
        (matches,) = tokens
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Mapping)")
        self.add_check("_coconut.len(" + item + ") == " + str(len(matches)))
        for x in range(len(matches)):
            k, v = matches[x]
            self.add_check(k + " in " + item)
            self.match(v, item + "[" + k + "]")

    def match_sequence(self, tokens, item):
        """Matches a sequence."""
        tail = None
        if len(tokens) == 2:
            series_type, matches = tokens
        else:
            series_type, matches, tail = tokens
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Sequence)")
        if tail is None:
            self.add_check("_coconut.len(" + item + ") == " + str(len(matches)))
        else:
            self.add_check("_coconut.len(" + item + ") >= " + str(len(matches)))
            if len(matches):
                splice = "[" + str(len(matches)) + ":]"
            else:
                splice = ""
            if series_type == "(":
                self.add_def(tail + " = _coconut.tuple(" + item + splice + ")")
            elif series_type == "[":
                self.add_def(tail + " = _coconut.list(" + item + splice + ")")
            else:
                raise CoconutInternalException("invalid series match type", series_type)
        self.match_all_in(matches, item)

    def match_iterator(self, tokens, item):
        """Matches an iterator."""
        tail = None
        if len(tokens) == 2:
            _, matches = tokens
        else:
            _, matches, tail = tokens
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Iterable)")
        itervar = self.get_temp_var()
        if tail is None:
            self.add_def(itervar + " = _coconut.tuple(" + item + ")")
        else:
            self.add_def(tail + " = _coconut.iter(" + item + ")")
            self.add_def(itervar + " = _coconut.tuple(_coconut_igetitem(" + tail + ", _coconut.slice(None, " + str(len(matches)) + ")))")
        with self.incremented():
            self.add_check("_coconut.len(" + itervar + ") == " + str(len(matches)))
            self.match_all_in(matches, itervar)

    def match_star(self, tokens, item):
        """Matches starred assignment."""
        head_matches, last_matches = None, None
        if len(tokens) == 1:
            middle = tokens[0]
        elif len(tokens) == 2:
            if isinstance(tokens[0], str):
                middle, last_matches = tokens
            else:
                head_matches, middle = tokens
        else:
            head_matches, middle, last_matches = tokens
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Iterable)")
        if head_matches is None and last_matches is None:
            self.add_def(middle + " = _coconut.list(" + item + ")")
        else:
            itervar = self.get_temp_var()
            self.add_def(itervar + " = _coconut.list(" + item + ")")
            with self.incremented():
                req_length = (len(head_matches) if head_matches is not None else 0) + (len(last_matches) if last_matches is not None else 0)
                self.add_check("_coconut.len(" + itervar + ") >= " + str(req_length))
                head_splice = str(len(head_matches)) if head_matches is not None else ""
                last_splice = "-" + str(len(last_matches)) if last_matches is not None else ""
                self.add_def(middle + " = " + itervar + "[" + head_splice + ":" + last_splice + "]")
                if head_matches is not None:
                    self.match_all_in(head_matches, itervar)
                if last_matches is not None:
                    for x in range(1, len(last_matches) + 1):
                        self.match(last_matches[-x], itervar + "[-" + str(x) + "]")

    def match_rsequence(self, tokens, item):
        """Matches a reverse sequence."""
        front, series_type, matches = tokens
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Sequence)")
        self.add_check("_coconut.len(" + item + ") >= " + str(len(matches)))
        if len(matches):
            splice = "[:" + str(-len(matches)) + "]"
        else:
            splice = ""
        if series_type == "(":
            self.add_def(front + " = _coconut.tuple(" + item + splice + ")")
        elif series_type == "[":
            self.add_def(front + " = _coconut.list(" + item + splice + ")")
        else:
            raise CoconutInternalException("invalid series match type", series_type)
        for x in range(len(matches)):
            self.match(matches[x], item + "[" + str(x - len(matches)) + "]")

    def match_msequence(self, tokens, item):
        """Matches a middle sequence."""
        series_type, head_matches, middle, _, last_matches = tokens
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Sequence)")
        self.add_check("_coconut.len(" + item + ") >= " + str(len(head_matches) + len(last_matches)))
        if len(head_matches) and len(last_matches):
            splice = "[" + str(len(head_matches)) + ":" + str(-len(last_matches)) + "]"
        elif len(head_matches):
            splice = "[" + str(len(head_matches)) + ":]"
        elif len(last_matches):
            splice = "[:" + str(-len(last_matches)) + "]"
        else:
            splice = ""
        if series_type == "(":
            self.add_def(middle + " = _coconut.tuple(" + item + splice + ")")
        elif series_type == "[":
            self.add_def(middle + " = _coconut.list(" + item + splice + ")")
        else:
            raise CoconutInternalException("invalid series match type", series_type)
        self.match_all_in(head_matches, item)
        for x in range(len(last_matches)):
            self.match(last_matches[x], item + "[" + str(x - len(last_matches)) + "]")

    def match_const(self, tokens, item):
        """Matches a constant."""
        (match,) = tokens
        if match in const_vars:
            self.add_check(item + " is " + match)
        else:
            self.add_check(item + " == " + match)

    def match_var(self, tokens, item):
        """Matches a variable."""
        (setvar,) = tokens
        if setvar != wildcard:
            if setvar in self.names:
                self.add_check(self.names[setvar] + " == " + item)
            else:
                self.add_def(setvar + " = " + item)
                self.names[setvar] = item

    def match_set(self, tokens, item):
        """Matches a set."""
        if len(tokens) == 1:
            match = tokens[0]
        else:
            raise CoconutInternalException("invalid set match tokens", tokens)
        self.add_check("_coconut.isinstance(" + item + ", _coconut.abc.Set)")
        self.add_check("_coconut.len(" + item + ") == " + str(len(match)))
        for const in match:
            self.add_check(const + " in " + item)

    def match_data(self, tokens, item):
        """Matches a data type."""
        data_type, matches = tokens
        self.add_check("_coconut.isinstance(" + item + ", " + data_type + ")")
        self.add_check("_coconut.len(" + item + ") == " + str(len(matches)))
        self.match_all_in(matches, item)

    def match_paren(self, tokens, item):
        """Matches a paren."""
        (match,) = tokens
        return self.match(match, item)

    def match_trailer(self, tokens, item):
        """Matches typedefs and as patterns."""
        if len(tokens) <= 1 or len(tokens) % 2 != 1:
            raise CoconutInternalException("invalid trailer match tokens", tokens)
        else:
            match, trailers = tokens[0], tokens[1:]
            for i in range(0, len(trailers), 2):
                op, arg = trailers[i], trailers[i + 1]
                if op == "is":
                    self.add_check("_coconut.isinstance(" + item + ", " + arg + ")")
                elif op == "as":
                    if arg in self.names:
                        self.add_check(self.names[arg] + " == " + item)
                    elif arg != wildcard:
                        self.add_def(arg + " = " + item)
                        self.names[arg] = item
                else:
                    raise CoconutInternalException("invalid trailer match operation", op)
            self.match(match, item)

    def match_and(self, tokens, item):
        """Matches and."""
        for match in tokens:
            self.match(match, item)

    def match_or(self, tokens, item):
        """Matches or."""
        for x in range(1, len(tokens)):
            self.duplicate().match(tokens[x], item)
        with self.only_self():
            self.match(tokens[0], item)

    def match(self, tokens, item):
        """Performs pattern-matching processing."""
        for flag, get_handler in self.matchers.items():
            if flag in tokens.keys():
                return get_handler(self)(tokens, item)
        raise CoconutInternalException("invalid inner match tokens", tokens)

    def out(self):
        out = ""
        closes = 0
        for checks, defs in self.checkdefs:
            if checks:
                out += "if (" + (") and (").join(checks) + "):\n" + openindent
                closes += 1
            if defs:
                out += "\n".join(defs) + "\n"
        out += match_check_var + " = True\n"
        out += closeindent * closes
        for other in self.others:
            out += other.out()
        return out