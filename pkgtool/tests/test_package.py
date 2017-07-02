import os
import time
import subprocess

import pkgtool

BASE_DIR = os.path.dirname(__file__)

def setup(d, name):
    
    subprocess.run(('git', 'init'), cwd=d)

    with open(os.path.join(d, 'Pytool'), 'w') as f:
        f.write("name = '{}'\n".format(name))
        f.write("pacakges = ['{}']\n".format(name))

def test():

    with tempfile.TemporaryDirectory as d:
   
        pkgtool.main(['pkgtool'])
    
        pkgtool.main(['pkgtool', d, 'version'])
   
        d_a = os.path.join(d, 'a')
        d_b = os.path.join(d, 'b')
        d_c = os.path.join(d, 'c')

        with open(os.path.join(d, 'test_package', 'hello.py'), 'w') as f:
            f.write('a = {}\n'.format(time.time()))
        
        pkgtool.main(['pkgtool', d, 'release', '--no-upload', '--no-term', '--no-recursion', '--no-input'])
       
    
