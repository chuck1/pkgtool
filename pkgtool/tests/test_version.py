
from pkgtool import Version

def _test_version(s):
    v = Version.from_string(s)
    print(v.to_string())
    for i in range(len(v.rel)):
        print(v.next(i).to_string())

    if v.pre:
        print(v.next_pre().to_string())
        print(v.remove_pre().to_string())
    print()

def test_version():
    _test_version('__version__ = \'1\'')
    _test_version('__version__ = \'1a0\'')
    _test_version('__version__ = \'1.2\'')
    _test_version('__version__ = \'1.2a0\'')
    _test_version('__version__ = \'1.2.3\'')
    _test_version('__version__ = \'1.2.3a0\'')
    _test_version('__version__ = \'1.2.3b0\'')
    _test_version('__version__ = \'1.2.3dev0\'')

