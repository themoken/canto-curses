from distutils.command.install_data import install_data
from distutils.core import setup, Extension

numeric_version = [ 0, 8, 2 ]
string_version = ".".join([ str(i) for i in numeric_version])

class canto_curses_install_data(install_data):
    def run(self):
        install_data.run(self)

        install_cmd = self.get_finalized_command('install')
        libdir = install_cmd.install_lib

        with open(libdir + '/canto_curses/main.py', 'r+') as f:
            d = f.read().replace("REPLACE_WITH_VERSION", "\"" + string_version + "\"")
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
              libraries = ['ncursesw'],
              library_dirs = ["/usr/local/lib", "/opt/local/lib"],
              include_dirs = ["/usr/local/include", "/opt/local/include"])],
      scripts=['bin/canto-curses'],
      data_files = [("share/man/man1/", ["man/canto-curses.1"])],
      cmdclass = { 'install_data' : canto_curses_install_data },
     )
