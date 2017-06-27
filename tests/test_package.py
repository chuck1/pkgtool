import os
import time

import pkgtool

BASE_DIR = os.path.dirname(__file__)

def test():
 
    d = os.path.join(BASE_DIR, '_test_package')
   
    if not os.path.exists(os.path.join(d, '.git')):
        subprocess.run(('git', 'init'), cwd=d)

    try:
        pkgtool.main(['pkgtool'])
    except: pass
    

    pkgtool.main(['pkgtool', d, 'version'])

    with open(os.path.join(d, 'test_package', 'hello.py'), 'w') as f:
        f.write('a = {}\n'.format(time.time()))
    
    pkgtool.main(['pkgtool', d, 'release', '--no-upload', '--no-term', '--no-recursion'])
   

