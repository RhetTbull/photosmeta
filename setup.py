#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# setup.py script for photosmeta
#
# Copyright (c) 2019 Rhet Turnbull, rturnbull+git@gmail.com
# All rights reserved.
#
# See LICENSE.md for license information

from setuptools import setup

# read the contents of README file
from os import path

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="photosmeta",
    version="1.1.0",
    description="Extract known metadata from Apple's Photos library and export this metadata to EXIF/IPTC/XMP fields in the photo file For example: Photos knows about Faces (personInImage) but does not preserve this data when exporting the original photo",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Rhet Turnbull",
    author_email="rturnbull+git@gmail.com",
    url="https://github.com/RhetTbull/",
    project_urls={"GitHub": "https://github.com/RhetTbull/photosmeta"},
    download_url="https://github.com/RhetTbull/photosmeta",
    packages=["photosmeta",],
    license="License :: OSI Approved :: MIT License",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: MacOS X",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python",
    ],
    install_requires=["osxphotos", "osxmetadata", "tqdm",],
    entry_points={"console_scripts": ["photosmeta=photosmeta.__main__:main"]},
)