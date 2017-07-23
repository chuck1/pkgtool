__version__ = '0.1b55'

import sys
from pprint import pprint
import toml
import argparse
import curses
import enum
import functools
import json
import re
import os
import sys
import subprocess
import tempfile
import traceback
from pprint import pprint
import shutil

from cached_property import cached_property
import termcolor
import toml

import pkgtool.version

#DIR = os.getcwd()

VISITED = []

def commented_lines(b):
    return [b'# ' + l for l in b.split(b'\n')]

def clean(f):
    def wrapped(self, *args, **kwargs):
        self.assert_clean()
        ret = f(self, *args, **kwargs)
        self.assert_clean()
        return ret
    return wrapped

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
        self.name = self.config['name']

        self._path_setup = None
        self._path_setup_lock = None
        self._path_pipfile = None
        self._path_pipfile_lock = None
        self._pipfile_lock = None
        self._executable = None

    def requirements(self):
        p = self.pipfile_lock
        for k, v in p['default'].items():
            if k.startswith('-e'):
                yield k
            else:
                if isinstance(v, str):
                    yield k + v
                else:
                    yield k + v['version'] 
        
    def requirements_dev(self):
        p = self.pipfile_lock
        yield from self.requirements()
        for k, v in p['develop'].items():
            if k.startswith('-e'):
                yield k
            else:
                if isinstance(v, str):
                    yield k + v
                else:
                    yield k + v['version'] 
        
    def write_requires(self, args, force=False):
        if os.path.exists(self.path_requirements):
            b = (os.path.getmtime(self.path_pipfile) > os.path.getmtime(self.path_requirements))
        else:
            b = True
        
        b = b or force
        if b:
            s = '\n'.join(self.requirements())
            with open(os.path.join(self.d, 'requirements.txt'), 'w') as f:
                f.write(s)

        return b

    def write_requirements_dev(self, args, force=False):
        if os.path.exists(self.path_requirements_dev):
            b = (os.path.getmtime(self.path_pipfile) > os.path.getmtime(self.path_requirements))
        else:
            b = True
        
        b = b or force
        if b:
            s = '\n'.join(self.requirements_dev())
            with open(self.path_requirements_dev, 'w') as f:
                f.write(s)

        return b

    def write_requires_and_commit(self, args):
        self.assert_clean()

        b = self.write_requirements_dev(args)
        b = self.write_requires(args)

        if b:
            if not self.is_clean():
                self.run(('git', 'add', 'requirements_dev.txt'), print_cmd=True)
                self.run(('git', 'add', 'requirements.txt'), print_cmd=True)
                self.run(('git', 'commit', '-m', 'PKGTOOL lock'), print_cmd=True)

        self.assert_clean()

    def _lock_pipfile(self, force=False):
        b = (os.path.getmtime(self.path_pipfile) > os.path.getmtime(self.path_pipfile_lock))
        b = b or force
        if b:
            self.run(('pipenv', 'lock'), print_cmd=True)
        return b

    @clean
    def lock_pipfile(self):
        b = self._lock_pipfile()
        if b:
            if not self.is_clean():
                self.run(('git', 'add', 'Pipfile.lock'), print_cmd=True)
                self.run(('git', 'commit', '-m', 'PKGTOOL lock'), print_cmd=True)

        return b

    def lock(self, args):
        self.lock_pipfile()

        self.write_requires_and_commit(args)

        if os.path.exists(self.path_setup_lock):
            if os.path.getmtime(self.path_setup_lock) > os.path.getmtime(self.path_setup):
                return
        with open(self.path_setup) as f:
            s = toml.loads(f.read())
        with open(self.path_setup_lock, 'w') as f:
            f.write(json.dumps(s, indent=4))
        
        self.run(('git', 'add', 'Setup.lock'), print_cmd=True)
        self.run(('git', 'commit', '-m', 'PKGTOOL lock setup'), print_cmd=True)
       
        self.assert_clean()

    def pyup_post(self, args):

        pipfile = self.pipfile

        p = pipfile['packages']
        
        print('pipfile:')
        pprint(p)
        print()
        
        shutil.copyfile(self.path_requirements, self.path_requirements_pyup)
        
        r0 = dict(self.read_requirements_pyup())
        
        print('pyup:')
        pprint(r0)
        print()

        input('press enter to coninute')
        
        differ=False
        for k, v in r0.items():
            if k in p:
                pv = p[k]
                if pv.startswith('=='):
                    if pv != v:
                        print('versions differ',k,pv,v)
                        p[k] = v
                        differ=True
        
        if differ:
            print('new pipfile:')
            pprint(pipfile)
        
            s = toml.dumps(pipfile)
        
            with open('Pipfile', 'w') as f:
                f.write(s)
        
        # check new cooked requirements agains requirements_pyup
        self._lock_pipfile(True)

        self.write_requires(args, True)
        
        r1 = dict(self.read_requirements())
        
        for k, v in r0.items():
            if k in r1:
                v1 = r1[k]
                if v1.startswith('=='):
                    if v1 != v:
                        print('versions differ',k,v1,v)
        

    def run(self, args, cwd=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, print_cmd=False, dry_run=False,
            shell=False):
        if cwd is None: cwd = self.d
        
        if print_cmd or dry_run:
            if shell:
                self.print_(args)
            else:
                self.print_(' '.join(args))
        if dry_run: return
        
        r = subprocess.run(args, stdout=stdout, stderr=stderr, cwd=cwd, shell=shell)
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

    @property
    def path_setup(self):
        if not self._path_setup:
            self._path_setup = os.path.join(self.d, 'Pytool')
        return self._path_setup

    @cached_property
    def path_requirements(self):
        return os.path.join(self.d, 'requirements.txt')

    @cached_property
    def path_requirements_dev(self):
        return os.path.join(self.d, 'requirements_dev.txt')

    @cached_property
    def path_requirements_pyup(self):
        return os.path.join(self.d, 'requirements_pyup.txt')

    @cached_property
    def path_setup_lock(self):
        return os.path.join(self.d, 'Setup.lock')

    @cached_property
    def path_pipfile(self):
        return os.path.join(self.d, 'Pipfile')

    @property
    def path_pipfile_lock(self):
        if not self._path_pipfile_lock:
            self._path_pipfile_lock = os.path.join(self.d, 'Pipfile.lock')
        return self._path_pipfile_lock
    
    @property
    def pipfile(self):
        with open(self.path_pipfile) as f:
            p = toml.loads(f.read())

        return p

    @property
    def pipfile_lock(self):
        b = self._lock_pipfile()
        if (not self._pipfile_lock) or b:
            with open(self.path_pipfile_lock) as f:
                self._pipfile_lock = json.loads(f.read())

        return self._pipfile_lock

    def _read_req_file(self, path):
        with open(path) as f:
            s = f.read()

        lst = s.strip().split('\n')

        for l in lst:
            if not l: continue
            m = re.match('^([\w-]+)(.*)$', l)
            yield m.group(1).lower(), m.group(2)

    def reax_requirements(self):
        yield from self._read_req_file(os.path.join(self.d, 'requirements.txt'))
     
    def read_requirements_pyup(self):
        yield from self._read_req_file(os.path.join(self.d, 'requirements_pyup.txt'))
    
    def pipenv_run(self, cmd, *args, **kwargs):
        self.run(('pipenv', 'run') + cmd, *args, **kwargs)

    def pip_install(self, name, version):
        if version.startswith('local '):
            self.pipenv_run(('pip3', 'install', '-e', version[6:]), print_cmd=True)
            return
        
        self.print_('{} {}'.format(repr(name), repr(version)))
        self.run(('pipenv', 'run', 'pip3', 'install', name + version), print_cmd=True)

    def pip_uninstall(self, name):
        self.run(('pipenv', 'run', 'pip3', 'uninstall', name, '-y'), 
                print_cmd=True)
        
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
                if m.group(1) == 'A ':
                    yield Package.FileStatus.Type.UNTRACKED, True, m.group(2)
                elif m.group(1) == ' M':
                    yield Package.FileStatus.Type.MODIFIED, False, m.group(2)
                elif m.group(1) == 'M ':
                    yield Package.FileStatus.Type.MODIFIED, True, m.group(2)
                elif m.group(1) == 'MM':
                    yield Package.FileStatus.Type.MODIFIED, True, m.group(2)
                elif m.group(1) == ' D':
                    yield Package.FileStatus.Type.DELETED, False, m.group(2)
                elif m.group(1) == 'D ':
                    yield Package.FileStatus.Type.DELETED, True, m.group(2)
                elif m.group(1) == '??':
                    yield Package.FileStatus.Type.UNTRACKED, False, m.group(2)
                else:
                    self.print_('unhandled code: {}'.format(repr(m.group(1))))
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

    def assert_clean(self):
        if not self.is_clean():
            self.print_('not clean')
            raise AssertionError()

    def clean_working_tree(self, args):
        if args.get('no_term', False):
            self.auto_commit('PKGTOOL auto commit all')
        else:
            if not self.is_clean():
                self.git_terminal()
        
        self.assert_clean()
    
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
            v = pkgtool.version.VersionProject.from_string(self, l[0])
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
        # exploring alternate method
        pipfile = self.read_pipfile()
        for k, v in pipfile.get('dev-packages', {}).items():
            m = re.match('-e (.*)', k)
            if m:
                if m.group(1) == '.':
                    continue

                d = os.path.normpath(os.path.join(self.d, m.group(1)))
                
                try:
                    pkg = Package(d)
                except:
                    continue
                
                pkg.current_version()
                yield pkg
        
    def print_(self, *args):
        print(termcolor.colored('{:<16}'.format(self.pkg), 'white', attrs=['bold']), *args)

    def spec_in_pipfile(self, pipfile, name, spec):
        if not 'packages' in pipfile:
            self.print_('Pipfile does not have a \'packages\' attribute')
            return False
        
        name1 = name.replace('_','-')
        name2 = name.replace('-','_')

        if name1 in pipfile['packages']:
            name = name1
        elif name2 in pipfile['packages']:
            name = name2
        else:
            self.print_('Pipfile \'packages\' does not contain {} or {}'.format(repr(name1), repr(name2)))
            return False
        
        s = pipfile['packages'][name]
        if s == spec:
            return True
        else:
            self.print_('Pipefile entry {} does not match {}'.format(repr(s), repr(spec)))
            return False

    def modify_pipfile(self, deps):
        with open(self.path_pipfile) as f:
            p = toml.loads(f.read())
        
        if not 'packages' in p:
            p['packages'] = {}
        
        for k, v in deps.items():
            k = k.replace('_','-')
            p['packages'][k] = v

        with open(self.path_pipfile, 'w') as f:
            f.write(toml.dumps(p))

    def pipenv_install_deps(self, args):
        self.print_('local deps')

        self.assert_clean()

        for pkg in self.gen_local_deps():

            v_string = pkg.current_version().to_string()
            spec = '==' + v_string
 
            pipfile = self.read_pipfile()
            
            if self.spec_in_pipfile(pipfile, pkg.name, spec):
                self.print_('{}{} already in Pipfile'.format(pkg.name, spec))
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

            deps = {}
            deps[pkg.name] = spec

            self.modify_pipfile(deps)

            if not self.is_clean():
                self.run(('git', 'add', 'Pipfile'), print_cmd=True)
                self.run(('git', 'commit', '-m', 'PKGTOOL update {} to {}'.format(pkg.pkg, v_string)), print_cmd=True)
            
            self.assert_clean()

        self.lock_pipfile()

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

        self.run(('git', 'commit', '-m', 'PKGTOOL change version from {} to {}'.format(
            v0.to_string(), v.to_string())), print_cmd=True)
        self.run(('git', 'tag', 'v{}'.format(v.to_string())), print_cmd=True)
        self.run(('git', 'push', 'origin', 'v{}'.format(v.to_string())), print_cmd=True)

    def release(self, args):
        """
        Ensure a clean working directory and then ``pipenv install`` the latest version 
        """

        # steps
        # make sure working tree is clean
        self.clean_working_tree(args)
        self.print_('working tree is clean')

        self.test(args)
        
        # pipenv install source versions of dependent project packages
        self.pipenv_install_deps(args)
        
        self.lock(args)
        
        self.assert_clean()

        # if clean, compare to version tag matching version in source
        if self.compare_ancestor_version():
            print('this branch is ahead of v{}'.format(self.current_version().to_string()))
            self.input_version_change(args)
            self.upload_wheel(args)
        
        self.run(('git','push'), print_cmd=True)

    def commit(self, args):
        # make sure working tree is clean
        if self.is_clean(): return

        self.clean_working_tree(args)
        self.print_('working tree is clean')
        self.run(('git','push'), print_cmd=True)
    
    def clear_requirements(self):
        with open(os.path.join(self.d, 'requirements.txt'), 'wb') as f:
            f.write(b'')

    def assert_head_at_version_tag(self):
        v = self.current_version()
        c0 = v.get_git_commit()
        c1 = self.get_git_commit_HEAD()
        if not (c0 == c1):
            raise Exception('HEAD is not at v{}'.format(v.to_string()))

    def wheel_filename(self):
        s = self.current_version().to_string()
        return self.pkg + '-' + s + '-py36-none-any.whl'

    def auto_commit(self, m):
        self.run(('git','add','--all'), print_cmd=True)
        self.run(('git','commit','-m',m), print_cmd=True)

    def build_wheel(self, args):
        self.assert_head_at_version_tag()

        shutil.rmtree(os.path.join(self.d, 'build'), ignore_errors=True)
        
        # TODO have config option for python version and build all necessary wheels
        self.run(('python3', 'setup.py', 'bdist_wheel', '--python-tag', 'py36'), print_cmd=True)
        self.run(('python3', 'setup.py', 'sdist'), print_cmd=True)
        
    def upload_wheel(self, args):
        self.build_wheel(args)

        s = self.current_version().to_string()
        
        wf1 = self.pkg + '-' + s + '-py36-none-any.whl'
        wf2 = self.pkg.replace('-','_') + '-' + s + '-py36-none-any.whl'

        tar_file = self.pkg + '-' + s + '.tar.gz'

        if os.path.exists(os.path.join(self.d, 'dist', wf1)):
            wf = wf1
        elif os.path.exists(os.path.join(self.d, 'dist', wf2)):
            wf = wf2
        else:
            raise Exception()
        
        self.run(('twine', 'upload', os.path.join('dist', wf)), print_cmd=True, dry_run=args.get('no_upload', False))
        self.run(('twine', 'upload', os.path.join('dist', tar_file)), print_cmd=True, dry_run=args.get('no_upload', False))

    def read_config(self):
        with open(os.path.join(self.d, 'Pytool')) as f:
            c = toml.loads(f.read())
        return c

    def test(self, args):
        # Create a clean environment based on Pipfile.
        # Modules required for testing should be in dev-packages.
        
        self.clean_working_tree(args)

        c = self.get_git_commit_HEAD().decode()
        f = os.path.join(self.d, '.dev', 'test', c)
        if os.path.exists(f):
            self.print_('tests already passed')
            return

        #self.run(('pipenv','run','pytest','--maxfail=1','--ff'), stdout=None, stderr=None, print_cmd=True)
        self.run(('pipenv','run','py.test','--cov=./', '-x', '--ff'), stdout=None, stderr=None, print_cmd=True)

        try:
            os.makedirs(os.path.dirname(f))
        except: pass
        with open(f, 'w') as fd:
            fd.write(' ')

    @property
    def executable(self):
        if self._executable is None:
            self._executable = os.path.join(self.run(('pipenv','--venv')).stdout.decode().strip(), 'bin', 'python3')
        return self._executable

    def dev(self, args):
        """
        setup dev environment
        """
        #self.run(('pipenv','--three'), stdout=None, stderr=None, print_cmd=True)
        #self.run(('pipenv','run','pip3','install','-r','requirements_setup.txt'), 
        #        stdout=None, stderr=None, print_cmd=True)
        #self.run(('pipenv','install','--dev'), stdout=None, stderr=None, print_cmd=True)
        
        a = dict(args)
        a.update({'dev':True})
        self.do_install(a)

    def docs(self):
        self.run((self.executable, '-m', 'sphinx', '-M', 'html', 'docs', 'docs/_build'), stdout=None, stderr=None, print_cmd=True)
        self.run((self.executable, '-m', 'sphinx', '-M', 'coverage', 'docs', 'docs/_build'), stdout=None, stderr=None, print_cmd=True)
        self.run((self.executable, '-m', 'sphinx', '-M', 'doctest', 'docs', 'docs/_build'), stdout=None, stderr=None, print_cmd=True)
        d = os.environ.get('LOCAL_DOCS_DIR', None)
        if d:
            self.run(('cp', '-r', 'docs/_build/html', os.path.join(d, self.pkg)))

    def run_(self, args):
        c = args.get('command')
        self.run(c, stdout=None, stderr=None, shell=True, print_cmd=True)

    @staticmethod
    def foreach(f, self, args):
        assert args is not None

        if self.pkg in VISITED: return
        VISITED.append(self.pkg)

        for pkg in self.gen_local_deps():
            Package.foreach(f, pkg, args)

        f(self, args)
    
def version_(pkg, args):
    print(pkg.current_version().to_string())
    pkg.compare_pipfile_lock_to_freeze(args)

def wheel(pkg, args):
    pkg.build_wheel(args)

def upload(pkg, args):
    pkg.upload_wheel(args)

def docs(pkg, args):
    pkg.docs()

def test(pkg, args):
    pkg.test(args)

def pipenv(pkg, args):
    pkg.pipenv(args)

def main(argv):
    
    parser = argparse.ArgumentParser(prog=argv[0])
    parser.add_argument('d', nargs='?', default=os.getcwd())

    subparsers = parser.add_subparsers()
    
    def help_(_, args):
        parser.print_help()
    
    parser.set_defaults(func=help_)

    parser_version = subparsers.add_parser('version')
    parser_version.set_defaults(func=version_)
    
    commands = [
            ('write_requires', Package.write_requires, []),
            ('pyup_post', Package.pyup_post, []),
            ('lock', Package.lock, []),
            ('test', Package.test, []),
            ('commit', Package.commit, []),
            ('release', Package.release, [
                (('--no_upload',), {'action': 'store_true'}),
                (('--no_term',), {'action': 'store_true'}),
                (('--no_input',), {'action': 'store_true'}),
                (('--no_recursion',), {'action': 'store_true'}),
                ]),
            ]
    
    for s, f, arguments in commands:
        subparser = subparsers.add_parser(s)
        for args, kwargs in arguments:
            subparser.add_argument(*args, **kwargs)
        subparser.set_defaults(func=functools.partial(Package.foreach, f))

    parser_run = subparsers.add_parser('run')
    parser_run.add_argument('-c', '--command')
    parser_run.set_defaults(func=functools.partial(Package.foreach, Package.run_))

    parser_wheel = subparsers.add_parser('wheel')
    parser_wheel.set_defaults(func=wheel)

    parser_upload = subparsers.add_parser('upload')
    parser_upload.set_defaults(func=upload)

    parser_docs = subparsers.add_parser('docs')
    parser_docs.set_defaults(func=docs)

    args = parser.parse_args(argv[1:])

    # TODO use args to possible use different directory
    pkg = Package(args.d)

    try:
        args.func(pkg, vars(args))
    except Exception as e:
        print(e)
        raise
        sys.exit(1)
    




