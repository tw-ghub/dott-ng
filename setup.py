# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022 Thomas Winkler <thomas.winkler@gmail.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
###############################################################################

import glob
import hashlib
import os
import shlex
import shutil
import ssl
import stat
import subprocess
import sys
import urllib.request
import tarfile
import zipfile
from typing import List
from zipfile import ZipFile
from datetime import date

import setuptools
from setuptools import Distribution
from wheel.bdist_wheel import bdist_wheel

build_version = os.environ.get('BUILD_VERSION')
if build_version is None:
    build_version = f'{date.today().strftime("%Y%m%d")}'


class CustomInstallCommand(bdist_wheel):

    script_path = os.path.dirname(os.path.realpath(__file__))
    data_folder_relative = 'dott_data'  # relative to this file
    data_folder = os.path.join(script_path, data_folder_relative)  # destination folder in python distribution
    data_apps_folder = os.path.join(data_folder, 'apps')

    def __init__(self, dist, check_files: bool = True):
        super().__init__(dist)

        mirror_url: str = os.environ.get('DEP_MIRROR_URL')

        self._gdb_url = 'https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v12.2.1-1.2/xpack-arm-none-eabi-gcc-12.2.1-1.2-win32-x64.zip'
        self._gdb_url_orig = self._gdb_url
        if mirror_url is not None:
            print(f'Using DEP_MIRROR_URL ({mirror_url}) for GCC Windows download...')
            # note: use local mirror (declared in build environment), if available
            self._gdb_url = f'{mirror_url}/xpack-arm-none-eabi-gcc-12.2.1-1.2-win32-x64.zip'
        self._gdb_version_info = 'gcc-arm-none-eabi-gcc-12.2.1-1.2-win32-x64'
        self._gdb_folder = os.path.join(CustomInstallCommand.data_apps_folder, 'gdb')
        self._gdb_dload_file = 'gdb_win32_amd64.zip'
        self._gdb_dload_file_sha256 = '5662a2d95bd5b28d24797709864fa8e1379a3bd103112f3c96a6c16db1e2e44a'
        self._gdb_dload_file_valid = False

        if check_files:
            self._check_dload_files()  # check if download files already exist and are valid

    def _check_dload_files(self) -> bool:
        if os.path.exists(self._gdb_dload_file):
            f = open(self._gdb_dload_file, "rb")
            data = f.read()
            file_hash = hashlib.sha256(data).hexdigest()
            if self._gdb_dload_file_sha256 == file_hash:
                print(f'{self._gdb_dload_file} exists and has valid checksum')
                self._gdb_dload_file_valid = True
            else:
                print(f'Removing corrupt {self._gdb_dload_file}.')
                os.remove(self._gdb_dload_file)

        return self._gdb_dload_file_valid

    def _print_progress(self, count, block_size, total_size):
        one = total_size / block_size // 100
        if count % one == 0:
            sys.stdout.write('.')
            sys.stdout.flush()

    def _unpack_gcc(self):
        gdb_files = ('arm-none-eabi-gdb',
                     'arm-none-eabi-gdb-py3',
                     'arm-none-eabi-addr2line',
                     'arm-none-eabi-gcov',
                     'arm-none-eabi-objcopy',
                     'arm-none-eabi-strip',
                     'arm-none-eabi-elfedit',
                     'arm-none-eabi-objdump',
                     'arm-none-eabi-gcov-dump',
                     'arm-none-eabi-readelf',
                     'arm-none-eabi-gcov-tool',
                     'arm-none-eabi-nm',
                     'arm-none-eabi-strings',
                     'libexec/libz',
                     'libexec/libncurses',
                     'libexec/libpython',
                     'libexec/libexpat',
                     'libexec/libiconv',
                     'libexec/libmpfr',
                     'libexec/libgmp',
                     'libexec/libstdc++',
                     'libexec/libgcc_s',
                     'distro-info/licenses',
                     'distro-info/CHANGELOG.md',
                     'README.md')

        with ZipFile(self._gdb_dload_file, 'r') as zipObj:
            file_names = zipObj.namelist()
            for file_name in file_names:
                if ('python' in file_name) and ('/test/' not in file_name):
                    zipObj.extract(file_name, self._gdb_folder)
                else:
                    for gdb_file in gdb_files:
                        if gdb_file in file_name:
                            zipObj.extract(file_name, self._gdb_folder)

        # FIXME: correct folder path
#        shutil.move(f'{self._gdb_folder}/bin/arm-none-eabi-gdb-py3.exe', f'{self._gdb_folder}/bin/arm-none-eabi-gdb-py.exe')

        with open(os.path.join(self._gdb_folder, 'version.txt'), 'w+') as f:
            f.write(f'GDB and support tools extracted from xPack GNU Arm Embedded GCC toolchain.\n')
            f.write(f'version: {self._gdb_version_info}\n')
            f.write(f'downloaded from: {self._gdb_url_orig}\n')
            f.write(f'Note: To save space only selected parts of the full package have been included.\n'
                    f'      No other modifications have been performed.\n'
                    f'      The license of GDB and its components can be found in distro-info/licenses.\n'
                    f'\n'
                    f'Special thanks to Liviu Ionescu for his excellent work to provide the xPack version of the toolchain!\n')


    def _write_version(self):
        global build_version
        with open(os.path.join(CustomInstallCommand.data_apps_folder, 'version.txt'), 'w+') as f:
            f.write(f'DOTT runtime apps\n')
            f.write(f'version: {build_version}\n')

    def run(self):
        # dependency fetching
        print('Fetching dependencies...')
        print('  GNU Arm Embedded providing GDB for Arm Cortex-M', end='')
        sys.stdout.flush()

        if not self._gdb_dload_file_valid:
            with urllib.request.urlopen(self._gdb_url, context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as u, open (self._gdb_dload_file, 'wb') as f:
                f.write(u.read())


        print(' [done]')

        if not self._check_dload_files():
            print("Downloaded files could not be verified (checksums don't match)")
            sys.exit(-1)

        # dependency unpacking
        print('Unpacking dependencies...')
        print('  Unpacking GDB from GNU Arm Embedded Toolchain...', end='')
        sys.stdout.flush()
        self._unpack_gcc()
        print('  [done]')

        # write runtime apps version
        self._write_version()

        # we are done with unpacking. now we can set the correct data_files (in setup() this is too early)
        self.distribution.data_files = self._get_package_data_files()
        super().run()

    def finalize_options(self):
        super().finalize_options()
        #self.root_is_pure = False
        self.plat_name_supplied=True
        self.plat_name='win_amd64'

    def _get_package_data_files(self) -> List:
        ret = []
        for root, dirs, files in os.walk(CustomInstallCommand.data_folder_relative):
            src_files = []
            root = root.replace('\\', '/')
            root = root.replace('\\\\', '/')
            for f in files:
                f = f.replace('\\', '/')
                f = f.replace('\\\\', '/')
                src_files.append(root + '/' + f)
            ret.append((root, src_files))

        return ret


class CustomInstallCommandLinuxAmd64(CustomInstallCommand):

    def __init__(self, dist):
        super().__init__(dist, check_files=False)

        mirror_url: str = os.environ.get('DEP_MIRROR_URL')

        self._gdb_url = 'https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v12.2.1-1.2/xpack-arm-none-eabi-gcc-12.2.1-1.2-linux-x64.tar.gz'
        self._gdb_url_orig = self._gdb_url
        if mirror_url is not None:
            # note: use local mirror (declared in build environment), if available
            print(f'Using DEP_MIRROR_URL ({mirror_url}) for GCC Linux download...')
            self._gdb_url = f'{mirror_url}/xpack-arm-none-eabi-gcc-12.2.1-1.2-linux-x64.tar.gz'
        self._gdb_version_info = 'gcc-arm-none-eabi-gcc-12.2.1-1.2-linux-x64'
        self._gdb_folder = os.path.join(CustomInstallCommandLinuxAmd64.data_apps_folder, 'gdb')
        self._gdb_dload_file = 'gdb_linux_amd64.tar.gz'
        self._gdb_dload_file_sha256 = '65b52009ff1b7f22f5e030cc04e17e5e7d7f2436a62488aca905062a71d3944c'
        self._gdb_dload_file_valid = False

        self._check_dload_files()  # check if download files already exist and are valid

    def _unpack_gcc(self):
        gdb_files = ('arm-none-eabi-gdb',
                     'arm-none-eabi-gdb-py3',
                     'arm-none-eabi-addr2line',
                     'arm-none-eabi-gcov',
                     'arm-none-eabi-objcopy',
                     'arm-none-eabi-strip',
                     'arm-none-eabi-elfedit',
                     'arm-none-eabi-objdump',
                     'arm-none-eabi-gcov-dump',
                     'arm-none-eabi-readelf',
                     'arm-none-eabi-gcov-tool',
                     'arm-none-eabi-nm',
                     'arm-none-eabi-strings',
                     'libexec/libz',
                     'libexec/libncurses',
                     'libexec/libpython',
                     'libexec/libexpat',
                     'libexec/libiconv',
                     'libexec/libmpfr',
                     'libexec/libgmp',
                     'libexec/libstdc++',
                     'libexec/libgcc_s',
                     'distro-info/licenses',
                     'distro-info/CHANGELOG.md',
                     'README.md')

        tar = tarfile.open(self._gdb_dload_file, 'r:gz')
        first_dir: str = tar.getmembers()[0].name.split('/')[0]
        gdb_folder_tmp = f'{self._gdb_folder}_tmp'

        for file_name in tar:
            if ('python' in file_name.name) and ('/test/' not in file_name.name):
                tar.extract(file_name, gdb_folder_tmp)
            else:
                for gdb_file in gdb_files:
                    if gdb_file in file_name.name:
                        tar.extract(file_name, gdb_folder_tmp)

        shutil.move(os.path.join(gdb_folder_tmp, first_dir), self._gdb_folder)
        shutil.rmtree(gdb_folder_tmp)

        shutil.move(f'{self._gdb_folder}/bin/arm-none-eabi-gdb-py3', f'{self._gdb_folder}/bin/arm-none-eabi-gdb-py')

        with open(os.path.join(self._gdb_folder, 'version.txt'), 'w+') as f:
            f.write(f'GDB and support tools extracted from xPack GNU Arm Embedded GCC toolchain.\n')
            f.write(f'version: {self._gdb_version_info}\n')
            f.write(f'downloaded from: {self._gdb_url_orig}\n')
            f.write(f'Note: To save space only selected parts of the full package have been included.\n'
                    f'      No other modifications have been performed.\n'
                    f'      The license of GDB and its components can be found in distro-info/licenses.\n'
                    f'\n'
                    f'Special thanks to Liviu Ionescu for his excellent work to provide the xPack version of the toolchain!\n')


    def finalize_options(self):
        super().finalize_options()
        #self.root_is_pure = False
        self.plat_name_supplied=True
        self.plat_name='manylinux2014_x86_64'


def _set_execperms_in_whl(dir: str, pattern: str):
    for name in glob.glob(os.path.join(dir, '*.whl')):
        name_tmp: str = name.replace('.whl', '_NEW.whl')

        # create temp file
        with open(name_tmp, 'w') as f:
            f.close()

        # open input and output whl (zip) files; set files matching pattern executable in output archive.
        zf_in = zipfile.ZipFile(name, 'r')
        zf_out = zipfile.ZipFile(name_tmp, 'w')
        zf_out.comment = zf_in.comment
        for item in zf_in.filelist:
            if pattern in item.filename:
                perm = item.external_attr >> 16 | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                item.external_attr = perm << 16
            zf_out.writestr(item, zf_in.read(item.filename))
        zf_out.close()
        zf_in.close()

        # remove the original whl and replace it with the new one
        os.remove(name)
        shutil.move(name_tmp, name)


# ----------------------------------------------------------------------------------------------------------------------
shared_classifiers = [
                  "Environment :: Console",
                  "License :: OSI Approved :: Apache Software License",
                  "Topic :: Software Development :: Testing",
                  "Topic :: Software Development :: Debuggers",
                  "Topic :: Software Development :: Embedded Systems"
              ]

shared_author_email = "thomas.winkler@gmail.com"

shared_author = "Thomas Winkler"

shared_url = "https://github.com/tw-ghub/dott-ng"

shared_install_requires = [
                       "dott-ng-runtime==1.12.0",
                       "pygdbmi==0.10.0.1",
                       "pylink-square==0.11.1",
                       "pytest",
                       "pytest-cov",
                       "pytest-instafail",
                       "pytest-repeat"
                   ]

def setup_dott_runtime():
    setuptools.setup(
        cmdclass={
            'bdist_wheel': CustomInstallCommand,
        },
        name="dott-ng-runtime",
        version=build_version,
        author=shared_author,
        author_email=shared_author_email,
        description="Runtime Environment for Debugger-based on Target Testing (DOTT)",
        long_description="",
        long_description_content_type="text/markdown",
        url=shared_url,
        packages=[],
        data_files=[],
        platforms=['nt'],
        include_package_data=True,
        classifiers=shared_classifiers,
        install_requires=[
        ],
        python_requires='>=3.8',
    )


def setup_dott_runtime_linux_amd64():
    setuptools.setup(
        cmdclass={
            'bdist_wheel': CustomInstallCommandLinuxAmd64,
        },
        name="dott-ng-runtime",
        version=build_version,
        author=shared_author,
        author_email=shared_author_email,
        description="Runtime Environment for Debugger-based on Target Testing (DOTT)",
        long_description="",
        long_description_content_type="text/markdown",
        url=shared_url,
        packages=[],
        data_files=[],
        platforms=['Linux'],
        include_package_data=True,
        shared_classifiers=shared_classifiers,
        install_requires=shared_install_requires,
        python_requires='>=3.8',
    )


def setup_dott():
    setuptools.setup(
        cmdclass={
        },
        name="dott-ng",
        version=build_version,
        author=shared_author,
        author_email=shared_author_email,
        description="Debugger-based on Target Testing (DOTT)",
        long_description="",
        long_description_content_type="text/markdown",
        url=shared_url,
        packages=['dottmi'],
        data_files=[],  # data_files are set in bdist_wheel.run (in setup() this is too early)
        platforms=[],
        include_package_data=False,
        classifiers=shared_classifiers,
        install_requires=shared_install_requires,
        python_requires='>=3.8',
    )


# cleanup folders
shutil.rmtree(CustomInstallCommand.data_folder_relative, ignore_errors=True)

if '--dott-runtime-win-amd64' in sys.argv:
    sys.argv.remove('--dott-runtime-win-amd64')
    setup_dott_runtime()
elif '--dott-runtime-linux-amd64' in sys.argv:
    sys.argv.remove('--dott-runtime-linux-amd64')
    setup_dott_runtime_linux_amd64()
    _set_execperms_in_whl(os.path.join(os.path.dirname(__file__), 'dist'), '/bin/')
else:
    setup_dott()
