__version__ = '0.1b38'

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

#DIR = os.getcwd()

VISITED = []

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
        return Version(self.rel + [0])

    def input_add_release_level_pre(self):
        assert (self.pre is None) and (self.suf is None)
        return Version(self.rel + [0], self.input_pre())

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

def commented_lines(b):
    return [b'# ' + l for l in b.split(b'\n')]

class Package(object):
    """
    Represents a python package project.

    .. note: To install the project from source, use dev-packages: ``pipenv install --dev -e .``

    :param d: root of project
    """
    def __init__(self, d):
        self.d = d
        self.config = self.read_config()
        self.pkg = self.config['name']

    def run(self, args, cwd=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, print_cmd=False, dry_run=False):
        if cwd is None: cwd = self.d
        
        if print_cmd or dry_run: self.print_(' '.join(args))
        if dry_run: return
        
        r = subprocess.run(args, stdout=stdout, stderr=stderr, cwd=cwd)
        #o, e = p.communicate()
        #print(r.stdout.decode())
        #print(r.stderr.decode())
        if r.returncode != 0:
            if r.stdout:
                print(r.stdout.decode())
            if r.stderr:
                print(r.stderr.decode())
            e = Exception('Error in {}'.format(repr(' '.join(args))))
            self.print_(e)
            raise e
        return r
    
    def run_shell(self, args, cwd=None):
        if cwd is None: cwd = self.d
        #print(args)
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, shell=True)
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

            print('  {}'.format(repr(l)))

            m = re.match('^(..)\s([\w+-/\.]+)$', l)
            
            if not m: raise Exception('failed to parse git status line: {} lines: {}'.format(repr(l), lines))
            
            if m:
                print('  {}'.format(repr(m.group(1))))
                if m.group(1) == ' M':
                    yield Package.FileStatus.Type.MODIFIED, False, m.group(2)
                elif m.group(1) == 'M ':
                    yield Package.FileStatus.Type.MODIFIED, True, m.group(2)
                elif m.group(1) == ' D':
                    yield Package.FileStatus.Type.DELETED, False, m.group(2)
                elif m.group(1) == 'D ':
                    yield Package.FileStatus.Type.DELETED, True, m.group(2)
                elif m.group(1) == '??':
                    yield Package.FileStatus.Type.UNTRACKED, False, m.group(2)
                else:
                    raise Exception('unhandled code: {}'.format(repr(m.group(1))))

    class FileStatus(object):
        class Type(enum.Enum):
            MODIFIED = 0
            DELETED = 1
            UNTRACKED = 2

        def __init__(self, pkg, type_, staged, filename):
            self.pkg = pkg
            self.type_ = type_
            self.staged = staged
            self.filename = filename
        
        def toggle_stage(self):
            if self.staged:
                self.pkg.run(('git','reset','HEAD',self.filename))
                self.staged = False
            else:
                self.pkg.run(('git','add',self.filename))
                self.staged = True

        def addstr(self, stdscr, i):
            if self.staged:
                attr = curses.A_BOLD
            else:
                attr = 0
            stdscr.addstr(i, 2, '{:8} {}'.format(self.type_.name, self.filename), attr)

    def gen_file_status(self):
        for code, staged, fn in self.git_status_lines():
            yield Package.FileStatus(self, code, staged, fn)

    def git_terminal(self):
        
        def main(stdscr):
            curses.curs_set(0)
            # Clear screen
            

            files = list(self.gen_file_status())
            if not files:
                curses.endwin()
                return
            
            w1 = curses.newwin(len(files), 100, 3, 0)
            
            cursor = 0
            
            def draw():
                stdscr.clear()
                
                # pacakge info
                stdscr.addstr(0, 0, self.pkg)

                # This raises ZeroDivisionError when i == 10.
                for i, f in zip(range(len(files)), files):
                    f.addstr(w1, i)
            
                w1.addstr(cursor, 0, '>', curses.A_STANDOUT)
        
                stdscr.refresh()
                w1.refresh()
        
            draw()

            while True:
                c = stdscr.getch()

                if c == curses.KEY_UP or c == 65:
                    w1.addstr(cursor, 0, ' ')
                    cursor = (cursor + 1) % len(files)
                    w1.addstr(cursor, 0, '>', curses.A_STANDOUT)
                elif c == curses.KEY_DOWN or c == 66:
                    w1.addstr(cursor, 0, ' ')
                    cursor = (cursor - 1 + len(files)) % len(files)
                    w1.addstr(cursor, 0, '>', curses.A_STANDOUT)
                elif c == 10:
                    f = files[cursor]
                    f.toggle_stage()
                    f.addstr(w1, cursor)
                elif c == ord('c'):
                    # commit
                    cnt = sum(1 for f in files if f.staged)
                    if cnt == 0:
                        stdscr.addstr(11, 0, 'nothing is staged', curses.A_STANDOUT)
                        continue
                    
                    curses.endwin()
                    self.do_commit(f for f in files if f.staged)
                    files = list(self.gen_file_status())
                    if not files:
                        curses.endwin()
                        break
                    draw()
                elif c == ord('d'):
                    # diff
                    f = files[cursor]

                    if not f.type_ == Package.FileStatus.Type.MODIFIED:
                        continue

                    curses.endwin()
                    r = self.run(('git','diff','HEAD',f.filename))
                    with tempfile.NamedTemporaryFile() as tf:
                        tf.write(r.stdout)
                        tf.flush()
                        subprocess.run(('less',tf.name))

                    draw()
                elif c == 27:
                    curses.endwin()
                    break
                else:
                    stdscr.addstr(10, 0, 'you pressed {}'.format(c), curses.A_STANDOUT)

                w1.refresh()
                stdscr.refresh()
        
        curses.wrapper(main)

    def do_commit(self, files):
        with tempfile.NamedTemporaryFile() as tf:
            
            r = self.run(('git', 'status'))
            lines = [b'', b''] + commented_lines(r.stdout)
            
            for f in files:
                if f.type_ == Package.FileStatus.Type.MODIFIED:
                    r = self.run(('git','diff','HEAD',f.filename))
                    lines += [b''] + commented_lines(r.stdout)
            
            b = b'\n'.join(lines)

            tf.write(b)
            tf.flush()
            
            self.run2(('vi', tf.name))
            
            r = self.run(('git', 'commit', '-F', tf.name, '--cleanup=strip'))

    def clean_working_tree(self, args):
        for pkg in self.gen_local_deps():
            pkg.clean_working_tree(args)
        
        if args.get('no_term', False):
            self.auto_commit('PKGTOOL auto commit all')
        else:
            self.git_terminal()
        
        r = self.run(('git', 'status', '--porcelain'))
        if r.stdout:
            raise Exception('working tree not clean')
    
    def is_clean(self):
        r = self.run(('git', 'status', '--porcelain'))
        return not bool(r.stdout)
    
    def commit_notes(self, out_diff):
        r = self.run(('git', 'status'))
        lines = [b'', b''] + commented_lines(r.stdout) + [b''] + commented_lines(out_diff)
        return b'\n'.join(lines)

    def current_version(self):
        fn = os.path.join(self.d, self.pkg, '__init__.py')
        with open(fn) as f:
            l = f.readlines()
        try:
            v = VersionProject.from_string(self, l[0])
        except:
            raise Exception('unable to parse version from {}'.format(fn))
        
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
        
        #print('{:8} '.format('v' + v.to_string()), c0)
        #print('{:8} '.format('HEAD'), c1)
        #print('{:8} '.format('ancestor'), c)

        # HEAD is at tag
        if (c == c1):
            self.print_('HEAD is at {}'.format(v.to_string()))
            return False
        else:
            self.print_('HEAD is ahread of v{}'.format(v.to_string()))
            return True
    
    def gen_local_deps(self):
        """
        :rtype: generator of Package objects
        """

        self.print_('parsing dev-packages')

        # exploring alternate method
        pipfile = self.read_pipfile()
        for k, v in pipfile['dev-packages'].items():
            m = re.match('-e (.*)', k)
            if m:
                self.print_(repr(k), repr(v))
                self.print_(repr(m.group(1)))
                
                if m.group(1) == '.':
                    continue

                d = os.path.join(self.d, m.group(1))
                pkg = Package(d)
                pkg.current_version()
                yield pkg
        
        return
        with open(os.path.join(self.d, 'LOCAL_DEPS.txt')) as f:
            for l in f:
                l = l.strip()
                if not l: continue
                d = os.path.join(self.d, l)
                pkg = Package(d)
                pkg.current_version()
                yield pkg

    def print_(self, *args):
        print(termcolor.colored('{:<16}'.format(self.pkg), 'white', attrs=['bold']), *args)

    def spec_in_pipfile(self, pipfile, pkg, v):
        if not 'packages' in pipfile:
            self.print_('Pipfile does not have a \'packages\' attribute')
            return False
        
        pkg1 = pkg.replace('_','-')
        pkg2 = pkg.replace('-','_')

        if pkg1 in pipfile['packages']:
            pkg = pkg1
        elif pkg2 in pipfile['packages']:
            pkg = pkg2
        else:
            self.print_('Pipfile \'packages\' does not contain {} or {}'.format(repr(pkg1), repr(pkg2)))
            return False
        
        s = pipfile['packages'][pkg]
        if s == ('>=' + v):
            return True
        else:
            self.print_('Pipefile entry {} does not match {}'.format(s, '>='+v))
            return False

    def pipenv_install_deps(self, args):
        self.print_('local deps')

        for pkg in self.gen_local_deps():

            v_string = pkg.current_version().to_string()
            spec = pkg.pkg + '>=' + v_string
 
            pipfile = self.read_pipfile()
            
            if self.spec_in_pipfile(pipfile, pkg.pkg, v_string):
                self.print_('{} already in Pipfile'.format(spec))
                continue

            d2 = os.path.join(pkg.d, 'dist')
            
            #pkg.run(('make', 'wheel'))
            self.print_('other package\'s root:', pkg.d)
            self.print_('spec = {}'.format(spec))
            
            wf = pkg.wheel_filename()
            #if not (wf in os.listdir(d2)):
            if not os.path.exists(os.path.join(d2, wf)):
                self.print_('wheel {} not in {}.'.format(wf, d2))
                self.print_('try to build wheel...')
            
                pkg.build_wheel(args)

                if not (wf in os.listdir(d2)):
                    e = Exception('building wheel did not produce expected wheel file...')
                    self.print_(e)
                    raise e

            self.run(('pipenv', 'install', os.path.join(d2, wf)), print_cmd=True)
            self.run(('pipenv', 'install', spec), print_cmd=True)

            s_lines = list(self.git_status_lines())
            if s_lines:
                if not (len(s_lines) == 1):
                    Exception(str(s_lines))
                if not ((s_lines[0][0] == 'M') and (s_lines[0][1] == 'Pipfile')):
                    Exception(str(s_lines))
            
                self.run(('git', 'add', 'Pipfile'), print_cmd=True)
                self.run(('git', 'commit', '-m', 'PKGTOOL update {} to {}'.format(pkg.pkg, v_string)), print_cmd=True)

    def assert_status(self, lines):
        s = set(self.git_status_lines())
        if not (s == lines):
            raise Exception('assertion failed {}=={}'.format(s, lines))

    def input_version_change(self, args):
        v0 = self.current_version()
        v = v0.prompt_change(no_input=args.get('no_input', False))

        fn0 = os.path.join(self.pkg, '__init__.py')
        fn = os.path.join(self.d, fn0)
        
        with open(fn) as f:
            lines = f.readlines()

        lines[0] = '__version__ = \'{}\'\n'.format(v.to_string())

        with open(fn, 'w') as f:
            f.write(''.join(lines))

        self.assert_status(set(((Package.FileStatus.Type.MODIFIED, False, fn0),)))

        self.run(('git', 'add', fn0))

        # should we do the prereqs from build_wheel here?
        self.reset_env_and_test()

        self.run(('git', 'commit', '-m', 'PKGTOOL change version from {} to {}'.format(v0.to_string(), v.to_string())), print_cmd=True)
        self.run(('git', 'tag', 'v{}'.format(v.to_string())), print_cmd=True)
        self.run(('git', 'push', 'origin', 'v{}'.format(v.to_string())), print_cmd=True)

    def reset_env_and_test(self):
        # reset virtualenv
        self.run(('pipenv', '--rm'), print_cmd=True)
        self.run(('pipenv', '--three'), print_cmd=True)
        # install pkgtool but do not add it to Pipfile
        self.run(('pipenv', 'run', 'pip3', 'install', 'pkgtool'), print_cmd=True)
        self.run(('pipenv', 'install'), print_cmd=True)
        self.run(('pipenv', 'install', '--dev', '-e', '.'), print_cmd=True)

        self.write_requirements()
        
        self.run(('git','add','--all'))


    def release(self, args):
        """
        Ensure a clean working directory and then ``pipenv install`` the latest version 
        """
        if self.pkg in VISITED:
            print('already visted')
            return
        VISITED.append(self.pkg)
        
        self.print_('pkgtool')

        if not args.get('no_recursion', False):
            for pkg in self.gen_local_deps():
                print(termcolor.colored(pkg.pkg, 'blue', attrs=['bold']))
                pkg.release(args)

        try:
            # steps
            # make sure working tree is clean
            self.clean_working_tree(args)
            self.print_('working tree is clean')
    
            # pipenv install source versions of dependent project packages
            self.pipenv_install_deps(args)
    
            # if clean, compare to version tag matching version in source
            if self.compare_ancestor_version():
                print('this branch is ahead of v{}'.format(self.current_version().to_string()))
                self.input_version_change(args)
                self.upload_wheel(args)
            
            # if not clean or at downstream commit, change version, commit, push, and upload
        except Exception as e:
            raise
            #print(e)
            #traceback.print_exc()
            #sys.exit(1)

    def commit(self, args):
        if self.pkg in VISITED:
            return
        VISITED.append(self.pkg)
        
        self.print_('pkgtool')

        for pkg in self.gen_local_deps():
            print(termcolor.colored(pkg.pkg, 'blue', attrs=['bold']))
            pkg.commit(args)

        # make sure working tree is clean
        self.clean_working_tree(args)
        self.print_('working tree is clean')
    
    def write_requirements(self):
        r = self.run(('pipenv', 'run', 'pip3', 'freeze'))
        
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

    def wheel_filename(self):
        s = self.current_version().to_string()
        return self.pkg + '-' + s + '-py3-none-any.whl'

    def auto_commit(self, m):
        self.run(('git','add','--all'), print_cmd=True)
        self.run(('git','commit','-m',m), print_cmd=True)

    def build_wheel(self, args):
        self.assert_head_at_version_tag()

        self.write_requirements()
        
        shutil.rmtree(os.path.join(self.d, 'build'), ignore_errors=True)

        self.run(('python3', 'setup.py', 'bdist_wheel'), print_cmd=True)
        
    def upload_wheel(self, args):
        self.build_wheel(args)

        s = self.current_version().to_string()
        
        wf1 = self.pkg + '-' + s + '-py3-none-any.whl'
        wf2 = self.pkg.replace('-','_') + '-' + s + '-py3-none-any.whl'
        
        if os.path.exists(os.path.join(self.d, 'dist', wf1)):
            wf = wf1
        elif os.path.exists(os.path.join(self.d, 'dist', wf2)):
            wf = wf2
        else:
            raise Exception()
        
        self.run(('twine', 'upload', os.path.join('dist', wf)), print_cmd=True, dry_run=args.get('no_upload', False))

    def read_config(self):
        with open(os.path.join(self.d, 'Pytool')) as f:
            c = toml.loads(f.read())
        return c
    def setup_args(self):
        c = self.read_config()
        
        with open(os.path.join(self.d, c['name'], '__init__.py')) as f:
            version = re.findall("^__version__ = '(.*)'", f.read())[0]
        
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
                'packages': c.get('packages', []),
                'zip_safe': False,
                'scripts': c.get('scripts',[]),
                'package_data': c.get('package_data',{}),
                'install_requires': install_requires,}
        
        return kwargs
    
    def test(self, args):
        self.run(('pipenv','run','pytest'), stdout=None, stderr=None)
        #self.run(('pipenv','run','pytest','--maxfail=1','--ff'), stdout=None, stderr=None)

    def docs(self):
        self.run(('make', '-C', 'docs', 'html'))
        self.run(('make', '-C', 'docs', 'coverage'))
        d = os.environ['LOCAL_DOCS_DIR']
        if d:
            self.run(('cp', '-r', 'docs/_build/html', os.path.join(d, self.pkg)))

def commit(pkg, args):
    pkg.commit(args)

def release(pkg, args):
    pkg.release(args)

def version(pkg, args):
    print(pkg.current_version().to_string())

def wheel(pkg, args):
    pkg.build_wheel(args)

def upload(pkg, args):
    pkg.upload_wheel(args)

def docs(pkg, args):
    pkg.docs()

def test(pkg, args):
    pkg.test(args)

def main(argv):
    
    parser = argparse.ArgumentParser(prog=argv[0])
    parser.add_argument('d', nargs='?', default=os.getcwd())

    subparsers = parser.add_subparsers()
    
    def help_(_, args):
        parser.print_help()
    
    parser.set_defaults(func=help_)

    parser_commit = subparsers.add_parser('commit')
    parser_commit.set_defaults(func=commit)

    parser_release = subparsers.add_parser('release')
    parser_release.add_argument('--no-upload', action='store_true', dest='no_upload')
    parser_release.add_argument('--no-term', action='store_true', dest='no_term')
    parser_release.add_argument('--no-input', action='store_true', dest='no_input')
    parser_release.add_argument('--no-recursion', action='store_true', dest='no_recursion')
    parser_release.set_defaults(func=release)
 
    parser_version = subparsers.add_parser('version')
    parser_version.set_defaults(func=version)

    parser_wheel = subparsers.add_parser('wheel')
    parser_wheel.set_defaults(func=wheel)

    parser_upload = subparsers.add_parser('upload')
    parser_upload.set_defaults(func=upload)

    parser_test = subparsers.add_parser('test')
    parser_test.set_defaults(func=test)

    parser_docs = subparsers.add_parser('docs')
    parser_docs.set_defaults(func=docs)

    print('pkgtool',__version__)
    print('argv={}'.format(argv))

    args = parser.parse_args(argv[1:])

    print('d={}'.format(repr(args.d)))

    # TODO use args to possible use different directory
    pkg = Package(args.d)

    try:
        args.func(pkg, vars(args))
    except Exception as e:
        print(e)
        raise
        sys.exit(1)
    


