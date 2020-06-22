#!/usr/bin/python
#
# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import codecs
import os
import sys
from setuptools import find_packages, setup


def readme():
  try:
    current_dir = os.path.abspath(os.path.dirname(__file__))
    longdescription_file = codecs.open(os.path.join(current_dir, 'README.rst'), encoding='utf8')
    try:
        file = longdescription_file.read()
    finally:
        file.close()
    # We let it die a horrible tracebacking death if reading the file fails.
    # We couldn't sensibly recover anyway: we need the long description.
    sys.path.insert(0, current_dir + os.sep + 'src')
    return longdescription_file
  except Exception:
    return None

def version():
    try:
        current_dir = os.path.abspath(os.path.dirname(__file__))
    except Exception:
        return None
    sys.path.insert(0, current_dir + os.sep + 'bitrot')
    from bitrot import VERSION
    release = ".".join(str(num) for num in VERSION)
    return release

REQUIRED_PACKAGES = [
    'futures',
    'progressbar2',
]


setup(
    name='bitrot',
    version=version(),
    author = u'Łukasz Langa',
    author_email = 'lukasz@langa.pl',
    description = ("Detects bit rotten files on the hard drive to save your "
                   "precious photo and music collection from slow decay."),
    long_description = readme(),
    url = 'https://github.com/ambv/bitrot/',
    keywords = 'file checksum database',
    platforms = ['any'],
    license = 'MIT',
    python_requires='>=2.7.0',
    install_requires=REQUIRED_PACKAGES,
    include_package_data=True,
    packages=find_packages(exclude=('tests', 'docs')),
    py_modules=['bitrot'],
    scripts = ['bitrot.py'],
    zip_safe = True,
    classifiers = [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python',
        'Topic :: System :: Filesystems',
        'Topic :: System :: Monitoring',
        'Topic :: Software Development :: Libraries :: Python Modules',
        ],
    entry_points={'console_scripts': ['bitrot = bitrot:run_from_command_line']})