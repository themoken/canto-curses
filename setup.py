from distutils.core import setup, Extension

setup(name='Canto-curses',
      version='0.8.0',
      description='Next-gen console RSS/Atom reader',
      author='Jack Miller',
      author_email='jack@codezen.org',
      url='http://codezen.org/canto',
      packages=['canto_curses'],
      ext_modules=[ Extension('canto_curses.widecurse',\
              sources = ['canto_curses/widecurse.c'],
              libraries = ['ncursesw'],
              library_dirs = ["/usr/local/lib", "/opt/local/lib"],
              include_dirs = ["/usr/local/include", "/opt/local/include"])],
      scripts=['bin/canto-curses'],
     )
