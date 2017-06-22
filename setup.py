import os
from setuptools import setup

import pytool

pkg = pytool.Package(os.getcwd())

setup(**pkg.setup_args())



