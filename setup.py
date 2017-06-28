#!/usr/bin/env python3

from distutils.command.install_data import install_data
from distutils.command.build_py import build_py
from distutils.core import setup, Extension
import subprocess
import glob
import os

string_version = "0.9.9"

class canto_curses_build_py(build_py):
    def run(self):
        os.utime("canto_curses/main.py", None)
        build_py.run(self)

class canto_curses_install_data(install_data):
    def run(self):
        try:
            git_hash = subprocess.check_output(["git", "describe"]).decode("UTF-8")[-9:-1]
        except Exception as e:
            print(e)
            git_hash = ""

        install_data.run(self)

        install_cmd = self.get_finalized_command('install')
        libdir = install_cmd.install_lib

        with open(libdir + '/canto_curses/main.py', 'r+') as f:
            d = f.read().replace("VERSION", "\"" + string_version + "\"")
            d = d.replace("GIT_HASH", "\"" + git_hash + "\"")
            f.truncate(0)
            f.seek(0)
            f.write(d)

setup(name='Canto-curses',
      version=string_version,
      description='Next-gen console RSS/Atom reader',
      author='Jack Miller',
      author_email='jack@codezen.org',
      license='GPLv2',
      download_url='http://codezen.org/static/canto-curses-' + string_version + ".tar.gz",
      url='http://codezen.org/canto-ng',
      packages=['canto_curses'],
      ext_modules=[ Extension('canto_curses.widecurse',\
              sources = ['canto_curses/widecurse.c'],
              libraries = ['ncursesw', 'readline'],
              library_dirs = ["/usr/local/lib", "/opt/local/lib"],
              include_dirs = ["/usr/local/include", "/opt/local/include"])],
      scripts=['bin/canto-curses'],
      data_files = [("share/man/man1/", ["man/canto-curses.1"]),
                    ("lib/canto/plugins/", glob.glob('plugins/*.py'))],
      cmdclass = {  'install_data' : canto_curses_install_data,
                    'build_py' : canto_curses_build_py},
     )
