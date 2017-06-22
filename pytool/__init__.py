__version__ = '0.1b2'

import toml
import argparse
import functools
import re
import os
import sys
import subprocess
import tempfile
import traceback
from pprint import pprint

#DIR = os.getcwd()

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

    def next(self, i):
        l = list(self.rel)[:i+1]
        l[i] += 1
        return Version(l)
    
    def next_add_pre(self, i, pre):
        v = self.next(i)
        v.pre = pre
        v.suf = None
        return v

    def input_next_add_pre(self, i):
        s = input('enter pre-release:')
        
        if not s: return self.next(i)

        m = re.match('(a|b|rc)(\d+)', s)
        s = m.group(1)
        n = int(m.group(2))

        return self.next_add_pre(i, Version.PreRelease(s, n))

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
    
    def prompt_change(self):
        options = list(self.version_change_options())
        
        print('current:', self.to_string())
        print('options:')
        for i, o in zip(range(len(options)), options):
            print('{:2}  {}'.format(i, o.s))
        
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
    def __init__(self, proj, rel, sv_code=None, sv_number=None):
        super(VersionProject, self).__init__(rel, sv_code, sv_number)
        self.proj = proj
    
    @classmethod
    def from_string(cls, proj, s):
        v = cls(proj, *Version.args_from_string(s))
        return v

    def get_git_commit(self):
        r = self.proj.run(('git', 'rev-parse', 'v'+self.to_string()))
        return r.stdout.strip()

def test(s):
    v = Version.from_string(s)
    print(v.to_string())
    for i in range(len(v.rel)):
        print(v.next(i).to_string())
    if v.sv_code:
        print(v.next_sv().to_string())
        print(v.remove_sv().to_string())
    print()

def tests():
    test('__version__ = \'1\'')
    test('__version__ = \'1a0\'')
    test('__version__ = \'1.2\'')
    test('__version__ = \'1.2a0\'')
    test('__version__ = \'1.2.3\'')
    test('__version__ = \'1.2.3a0\'')
    test('__version__ = \'1.2.3b0\'')
    test('__version__ = \'1.2.3dev0\'')



def commented_lines(b):
    return [b'# ' + l for l in b.split(b'\n')]




class Package(object):
    def __init__(self, d):
        self.d = d
        self.pkg = os.path.split(self.d)[1]

    def run(self, args, cwd=None):
        if cwd is None: cwd = self.d
        print(' '.join(args))
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        #o, e = p.communicate()
        #print(r.stdout.decode())
        #print(r.stderr.decode())
        if r.returncode != 0:
            raise Exception('Error in {}:\n{}\n{}'.format(repr(' '.join(args)), r.stdout.decode(), r.stderr.decode()))
        return r
    
    def run2(self, args, cwd=None):
        if cwd is None: cwd = self.d
        r = subprocess.run(args, cwd=cwd)
        #o, e = p.communicate()
        print(' '.join(args))
        return r

    def read_pipfile(self):
        with open(os.path.join(self.d, 'Pipfile')) as f:
            config = toml.loads(f.read())
        pprint(config)
        return config

    def get_git_commit_HEAD(self):
        r = self.run(('git', 'rev-parse', 'HEAD'))
        return r.stdout.strip()
    
    def git_status_lines(self):
        r = self.run(('git', 'status', '--porcelain'))
        lines = r.stdout.split(b'\n')
        for l in lines:
            if not l: continue

            l = l.decode()

            m = re.match('^\s(\w+)\s([\w+/\.]+)', l)
            
            if not m: raise Exception('failed to parse git status line: {} lines: {}'.format(repr(l), lines))
            
            if m:
                if m.group(1) == 'M':
                    yield m.group(1), m.group(2)
                else:
                    Exception('unhandled code: {}'.format(m.group(1)))
           
    def clean_working_tree(self):
        r = self.run(('git', 'status', '--porcelain'))
        
        lines = r.stdout.split(b'\n')
    
        for l in lines:
            m = re.match('^\s(\w+)\s([\w+/\.]+).*', l.decode())
            if m:
                if m.group(1) == 'M':
                    print('modified: {}'.format(m.group(2)))
    
                    r = self.run(('git','diff', m.group(2)))
    
                    self.run(('git', 'add', m.group(2)))
                    
                    with tempfile.NamedTemporaryFile() as f:
                        b = self.commit_notes(r.stdout)
                        f.write(b)
                        f.flush()
                        
                        self.run2(('vi', f.name))
                        
                        r = self.run(('git', 'commit', '-F', f.name, '--cleanup=strip'))
    
                        #print('out:',r.stdout.decode())
                        #print('err:',r.stderr.decode())
                        #print('rc:',r.returncode)
    
                    if r.returncode != 0:
                        # unstage
                        self.run(('git', 'reset', 'HEAD', m.group(2)))
                        raise Exception('working tree not clean')
    
            r = self.run(('git', 'status', '--porcelain'))
            if r.stdout:
                raise Exception('working tree not clean')
    
            #run2(('vi', temp, '>', '/dev/tty'))
            #run2(('vi', temp))
    
    def is_clean(self):
        r = self.run(('git', 'status', '--porcelain'))
        return not bool(r.stdout)
    
    def commit_notes(self, out_diff):
        r = self.run(('git', 'status'))
        lines = [b'', b''] + commented_lines(r.stdout) + [b''] + commented_lines(out_diff)
        return b'\n'.join(lines)

    def current_version(self):
        with open(os.path.join(self.d, self.pkg, '__init__.py')) as f:
            l = f.readlines()

        v = VersionProject.from_string(self, l[0])
        return v

    def compare_ancestor_version(self):
        """
        return True if HEAD differs from tag corresponding to current version
        return False if they are the same
        """
    
        v = self.current_version()
        
        r = self.run(('git', 'merge-base', 'HEAD', 'v'+v.to_string()))
    
        c = r.stdout.strip()
        
        c1 = self.get_git_commit_HEAD()
        
        c0 = v.get_git_commit()

        if not (c == c0):
            Exception('tag v{} is not ancestor of HEAD')
        
        print('{:8} '.format('v' + v.to_string()), c0)
        print('{:8} '.format('HEAD'), c1)
        print('{:8} '.format('ancestor'), c)

        # HEAD is at tag
        if (c == c1):
            print('HEAD is at {}'.format(v.to_string()))
            return False
        else:
            print('HEAD is ahread of v{}'.format(v.to_string()))
            return True

    def pipenv_install_deps(self):
        with open(os.path.join(self.d, 'LOCAL_DEPS.txt')) as f:
            b = f.read()
            b = b.strip()
            lines = b.split('\n')

        pipfile = self.read_pipfile()
        
        print('local deps')
        print(lines)
        for l in lines:
            if not l: continue

            d1 = os.path.join(os.path.split(self.d)[0], l)
            
            foo = Package(d1)
            v_string = foo.current_version().to_string()
            spec = l + '==' + v_string
            
            if pipfile['packages'][l] == ('==' + v_string):
                print('{} already in Pipfile'.format(spec))
                continue

            d2 = os.path.join(d1, 'dist')
            
            foo.run(('make', 'wheel'))

            print(d1)
            print(d2)
            print(os.listdir(d2)[0])
            print('spec = {}'.format(spec))

            wheel_file = os.path.join(d2, os.listdir(d2)[0])

            self.run(('pipenv', 'install', wheel_file))
            self.run(('pipenv', 'install', spec))

            s_lines = list(self.git_status_lines())
            if s_lines:
                if not (len(s_lines) == 1):
                    Exception(str(s_lines))
                if not ((s_lines[0][0] == 'M') and (s_lines[0][1] == 'Pipfile')):
                    Exception(str(s_lines))
            
                self.run(('git', 'add', 'Pipfile'))
                self.run(('git', 'commit', '-m', '\'update {} to {}\''.format(l, v_string)))

    def assert_status(self, lines):
        s = set(self.git_status_lines())
        if not (s == lines):
            raise Exception('assertion failed {}=={}'.format(s, lines))

    def input_version_change(self):
        v0 = self.current_version()
        v = v0.prompt_change()

        fn0 = os.path.join(self.pkg, '__init__.py')
        fn = os.path.join(self.d, fn0)
        
        with open(fn) as f:
            lines = f.readlines()

        lines[0] = '__version__ = \'{}\'\n'.format(v.to_string())

        with open(fn, 'w') as f:
            f.write(''.join(lines))

        self.assert_status(set((('M', fn0),)))

        self.run(('git', 'add', fn0))
        self.run(('git', 'commit', '-m', '\'change version from {} to {}\''.format(v0.to_string(), v.to_string())))
        self.run(('git', 'tag', 'v{}'.format(v.to_string())))
        self.run(('git', 'push', 'origin', 'v{}'.format(v.to_string())))

    def commit(self, args):
        try:
            # steps
            # make sure working tree is clean
            self.clean_working_tree()
            print('working tree is clean')
    
            # pipenv install source versions of dependent project packages
            self.pipenv_install_deps()
    
            # if clean, compare to version tag matching version in source
            if self.compare_ancestor_version():
                print('this branch is ahead of v{}'.format(self.current_version().to_string()))
                if input_yn('do you want to update the version number?', 'n'):
                    self.input_version_change()
            
            # if not clean or at downstream commit, change version, commit, push, and upload
        except Exception as e:
            print(e)
            traceback.print_exc()
        pass
    
    def write_requirements(self):
        r = subprocess.run(('pipenv', 'run', 'pip3', 'freeze'), stdout=subprocess.PIPE)
        print(r.stdout.decode())
    
        with open(os.path.join(self.d, 'requirements.txt'), 'wb') as f:
            for l in r.stdout.split(b'\n'):
                if b'git+' in l: continue
                f.write(l+b'\n')

    def assert_head_at_version_tag(self):
        v = self.current_version()
        c0 = v.get_git_commit()
        c1 = self.get_git_commit_HEAD()
        if not (c0 == c1):
            raise Exception('HEAD is not at v{}'.format(v.to_string()))

    def build_wheel(self):
        self.assert_head_at_version_tag()

        self.run('mkdir -p dist'.split(' '))
        self.run('rm -f dist/*whl'.split(' '))
        self.run('python3 setup.py bdist_wheel'.split(' '))
        
    def upload_wheel(self):
        self.build_wheel()
        
        self.run('twine upload dist/*whl'.split(' '))

    def setup_args(self):
    
        with open(os.path.join(self.d, 'Pytool')) as f:
            c = toml.loads(f.read())
        
        with open(os.path.join(self.d, c['name'], '__init__.py')) as f:
            version = re.findall("^__version__ = '(.*)'", f.read())[0]
        
        self.write_requirements()

        with open(os.path.join(self.d, 'requirements.txt')) as f:
            install_requires=[l.strip() for l in f.readlines()]
    
        kwargs = {
                'name': c['name'],
                'version': version,
                'description': c['description'],
                'url': c['url'],
                'author': c['author'],
                'author_email': c['author_email'],
                'license': c['license'],
                'packages': c['packages'],
                'zip_safe': False,
                'scripts': c['scripts'],
                'package_data': c['package_data'],
                'install_requires': install_requires,}
        
        return kwargs

def commit(pkg, args):
    pkg.commit(args)

def version(pkg, args):
    print(pkg.current_version().to_string())

def wheel(pkg, args):
    pkg.build_wheel()

def main(argv):
    
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    
    def help_(_, args):
        parser.print_help()

    parser.set_defaults(func=help_)

    parser_commit = subparsers.add_parser('commit')
    parser_commit.set_defaults(func=commit)
 
    parser_version = subparsers.add_parser('version')
    parser_version.set_defaults(func=version)

    parser_wheel = subparsers.add_parser('wheel')
    parser_wheel.set_defaults(func=wheel)
    
    args = parser.parse_args()
    
    # TODO use args to possible use different directory
    pkg = Package(os.getcwd())

    args.func(pkg, args)
    
    
    


