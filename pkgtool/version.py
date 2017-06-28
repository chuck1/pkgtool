__version__ = '0.1b47'

import argparse
import curses
import enum
import functools
import re
import os
import sys
import subprocess
import tempfile
import traceback
from pprint import pprint
import shutil

import termcolor
import toml

class Option(object):
    def __init__(self, c, s=None):
        if s is None: s = c().to_string()
        self.c = c
        self.s = s
    def __call__(self):
        return self.c()

def input_yn(s, default):
    while True:
        s = input('{} (y/n) [{}]:'.format(s, default))
        s = s.lower()
        
        if s == '': s = default

        if s == 'y':
            return True
        elif s == 'n':
            return False
        else:
            print('invalid entry')

class Version(object):
    class PreRelease(object):
        def __init__(self, s, n):
            if not s in ('a','b','rc'): raise Exception('invalid pre-release: {}'.format(s))
            self.s, self.n = s, n
        def next(self):
            return Version.PreRelease(self.s, self.n + 1)
        def to_string(self):
            return self.s + str(self.n)

    class Suffix(object):
        def __init__(self, s, n):
            if not s in ('post','dev'): raise Exception('invalid suffix: {}'.format(s))
            self.s, self.n = s, n
        def next(self):
            return Suffix(self.s, self.n + 1)
        def to_string(self):
            return self.s + str(self.n)

    def __init__(self, rel, pre=None, suf=None):
        self.rel = rel
        self.pre = pre
        self.suf = suf
    
    def next_pre(self):
        return Version(list(self.rel), self.pre.next())

    def remove_pre(self):
        return Version(list(self.rel))

    def next(self, i, pre=None):
        l = list(self.rel)[:i+1]
        l[i] += 1
        return Version(l, pre=pre)
    
    def input_pre(self):
        s = input('enter pre-release:')
        if not s: return None
        m = re.match('(a|b|rc)(\d+)', s)
        s = m.group(1)
        n = int(m.group(2))
        return Version.PreRelease(s, n)

    def input_next_add_pre(self, i):
        pre = self.input_pre()
        return self.next(i, pre)
    
    def add_release_level(self):
        assert (self.pre is None) and (self.suf is None)
        return Version(self.rel + [1])

    def input_add_release_level_pre(self):
        assert (self.pre is None) and (self.suf is None)
        return Version(self.rel + [1], self.input_pre())

    def version_change_options(self):
        """
        yields callables that returns Version objects that could succeed this version
        """

        if self.suf is not None: raise Exception('suffix not yet supported')
        
        if self.pre:
            yield Option(self.next_pre)
            yield Option(self.remove_pre)

        for i in range(len(self.rel)):
            yield Option(functools.partial(self.input_next_add_pre, i), self.next(i).to_string())
        
        if (self.pre is None) and (self.suf is None):
            if len(self.rel) < 3:
                yield Option(self.input_add_release_level_pre, self.add_release_level().to_string())

    def prompt_change(self, no_input=False):
        options = list(self.version_change_options())
        
        print('current:', self.to_string())
        print('options:')
        for i, o in zip(range(len(options)), options):
            print('{:2}  {}'.format(i, o.s))
        
        if no_input:
            s = None
        else:
            s = input('choice (0-{}) [0]:'.format(len(options)-1))

        if s:
            i = int(s)
        else:
            i = 0

        o = options[i]

        v = o()
        
        print('new version:', v.to_string())
        
        return v

    @classmethod
    def args_from_string(cls, s):
        m = re.match('__version__ = \'(\d+)(\.(\d+))?(\.(\d+))?((a|b|rc)(\d+))?.*', s)
        g = m.groups()
        v = [int(g[0])]
        if g[2]:
            v.append(int(g[2]))
        if g[4]:
            v.append(int(g[4]))
        
        if g[6]:
            pre = Version.PreRelease(g[6], int(g[7]))
        else:
            pre = None
        
        suf = None

        return (v, pre, suf)

    @classmethod
    def from_string(cls, s):
        args = cls.args_from_string(s)
        return cls(*args)   

    def to_string(self):
        return '.'.join(str(l) for l in self.rel) + (self.pre.to_string() if self.pre else '') + (self.suf.to_string() if self.suf else '')

class VersionProject(Version):
    """
    Version object that stores a refernce to a Project object
    """
    def __init__(self, proj, rel, pre=None, suf=None):
        super(VersionProject, self).__init__(rel, pre, suf)
        self.proj = proj
    
    @classmethod
    def from_string(cls, proj, s):
        v = cls(proj, *Version.args_from_string(s))
        return v

    def get_git_commit(self):
        r = self.proj.run(('git', 'rev-parse', 'v'+self.to_string()))
        return r.stdout.strip()


