#!/usr/bin/env python3

# photosmeta
# Copyright (c) 2019 Rhet Turnbull <rturnbull+git@gmail.com>
#
# This script will extract known metadata from Apple's Photos library and
# write this metadata to EXIF/IPTC/XMP fields in the photo file
# For example: Photos knows about Faces (personInImage) but does not
# preserve this data when exporting the original photo

# Metadata currently extracted and where it is placed:
# Photos Faces --> XMP:PersonInImage, XMP:Subject
# Photos keywords --> XMP:TagsList, IPTC:Keywords
# Photos title --> XMP:Title
# Photos description --> IPTC:Caption-Abstract, EXIF:ImageDescription, XMP:Description

# title and description are overwritten in the destination file
# faces and keywords are merged with any data found in destination file (removing duplicates)

# Dependencies:
#   exiftool by Phil Harvey:
#       https://www.sno.phy.queensu.ca/~phil/exiftool/

# This code was inspired by photo-export by Patrick Fältström see:
#   https://github.com/patrikhson/photo-export
#   Copyright (c) 2015 Patrik Fältström <paf@frobbit.se>

# ## THINGS TODO ###
# TODO: add missing option to list missing photos
# TODO: add --version
# todo: progress bar for photos to process (use tqdm)
# todo: do ratings? XMP:Ratings, XMP:RatingsPercent
# todo: position data (lat / lon)
# todo: option to export then apply tags (e.g. don't tag original)
# todo: cleanup single/double quotes
# todo: standardize/cleanup exception handling in helper functions
# todo: how are live photos handled
# todo: use -stay_open with exiftool to aviod repeated subprocess calls
# todo: right now, options (keyword, person, etc) are OR...add option for AND
#         e.g. only process photos in album=Test AND person=Joe
# todo: options to add:
# --save_backup (save original file)
# --export (export file instead of edit in place)
# todo: test cases:
#     1) photo edited in Photos
#     2) photo edited in external editor
#     3) photo where original in cloud but not on device (RKMaster.isMissing)
# todo: Add other xattr metadata such as kMDItemAlbum?
#   see: https://developer.apple.com/library/archive/documentation/CoreServices/Reference/MetadataAttributesRef/Reference/CommonAttrs.html#//apple_ref/doc/uid/TP40001694-SW1

# TODO: cleanup import list...many of these not needed for new version with osxphotos
# if _dbfile is None:
#     library_path = get_photos_library_path()
#     print("library_path: " + library_path)
#     # TODO: verify library path not None
#     _dbfile = os.path.join(library_path, "database/photos.db")
#     print(_dbfile)

# # filename = _dbfile
# # verbose("filename = %s" % filename)

# # TODO: replace os.path with pathlib
# # TODO: clean this up -- we'll already know library_path
# library_path = os.path.dirname(filename)
# (library_path, tmp) = os.path.split(library_path)
# masters_path = os.path.join(library_path, "Masters")
# verbose("library = %s, masters = %s" % (library_path, masters_path))

# if not check_file_exists(filename):
#     sys.exit("_dbfile %s does not exist" % (filename))

# verbose("databse filename = %s" % filename)


import argparse
import json
import os.path
import pprint
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import osxmetadata
import osxphotos
from tqdm import tqdm

# TODO: cleanup globals  -- most not needed now
# Globals
_version = "1.1.0"
_debug = False
_exiftool = None  # will hold path to exiftools
_args = None  # command line args as processed by argparse
_verbose = False  # print verbose output
_dbfile = None  # will hold path to the Photos sqlite3 database file


# custom argparse class to show help if error triggered
class MyParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        self.print_help()
        sys.exit(2)


def process_arguments():
    global _args
    global _verbose
    global _dbfile
    global _debug

    # Setup command line arguments
    parser = MyParser()
    # one required argument: path to database file
    # parser.add_argument("DATABASE_FILE", help="path to Photos database file")
    parser.add_argument(
        "--database", help="database file [will default to Photos default file]"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="print verbose output",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        default=False,
        help="Do not prompt before processing",
    )
    parser.add_argument(
        "--debug", action="store_true", default=False, help="enable debug output"
    )  # TODO: eventually remove this
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help="list files to be updated but do not actually udpate meta data",
    )
    parser.add_argument(
        "--keyword", action="append", help="only process files containing keyword"
    )
    parser.add_argument(
        "--album", action="append", help="only process files contained in album"
    )
    parser.add_argument(
        "--person",
        action="append",
        help="only process files         tagged with person",
    )
    parser.add_argument(
        "--uuid", action="append", help="only process file matching UUID"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="export all photos in the database",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        default=False,
        help="modify all photos in place (don't create backups). "
        "If you don't use this option, exiftool will create a backup image "
        "with format filename.extension_original in the same folder as the original image",
    )
    parser.add_argument(
        "--xattrtag",
        action="store_true",
        default=False,
        help="write tags/keywords to file's extended attributes (kMDItemUserTags) "
        "so you can search in spotlight using 'tag:' "
        "May be combined with -xattrperson "
        "CAUTION: this overwrites all existing kMDItemUserTags (to be fixed in future release)",
    )
    parser.add_argument(
        "--xattrperson",
        action="store_true",
        default=False,
        help="write person (faces) to file's extended attributes (kMDItemUserTags) "
        "so you can search in spotlight using 'tag:' "
        "May be combined with --xattrtag "
        "CAUTION: this overwrites all existing kMDItemUserTags (to be fixed in future release)",
    )

    parser.add_argument(
        "--list",
        action="append",
        choices=["keyword", "album", "person"],
        help="list keywords, albums, persons found in database then exit: "
        + "--list=keyword, --list=album, --list=person",
    )

    # if no args, show help and exit
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    _args = parser.parse_args()
    _verbose = _args.verbose
    _dbfile = _args.database
    _debug = _args.debug

    if _args.keyword is not None:
        print("keywords: " + " ".join(_args.keyword))


def check_file_exists(filename):
    # returns true if file exists and is not a directory
    # otherwise returns false

    filename = os.path.abspath(filename)
    return os.path.exists(filename) and not os.path.isdir(filename)


def verbose(s):
    # print output only if global _verbose is True
    if _verbose:
        tqdm.write(s)


def get_exiftool_path():
    global _exiftool
    result = subprocess.run(["which", "exiftool"], stdout=subprocess.PIPE)
    exiftool_path = result.stdout.decode("utf-8")
    if _debug:
        print("exiftool path = %s" % (exiftool_path))
    if exiftool_path is not "":
        return exiftool_path.rstrip()
    else:
        print(
            "Could not find exiftool. Please download and install from "
            "https://www.sno.phy.queensu.ca/~phil/exiftool/",
            file=sys.stderr,
        )
        errstr = "Could not find exiftool"
        sys.exit(errstr)


def get_exif_info_as_json(photopath):
    # get exif info from file as JSON via exiftool

    if not check_file_exists(photopath):
        raise ValueError("Photopath %s does not appear to be valid file" % photopath)
        return

    _exiftool = get_exiftool_path()
    exif_cmd = [_exiftool, "-G", "-j", "-sort", photopath]

    try:
        proc = subprocess.run(exif_cmd, check=True, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        sys.exit("subprocess error calling command %s %s: " % (exif_cmd, e))
    else:
        if _debug:
            print("returncode: %d" % proc.returncode)
            print(
                "Have {} bytes in stdout:\n{}".format(
                    len(proc.stdout), proc.stdout.decode("utf-8")
                )
            )

    j = json.loads(proc.stdout.decode("utf-8").rstrip("\r\n"))

    return j


def build_list(lst):
    # takes an array of elements that may be a string or list
    #  and returns a list of all items appended
    tmplst = []
    for x in lst:
        if x is not None:
            if isinstance(x, list):
                tmplst = tmplst + x
            else:
                tmplst.append(x)
    return tmplst


def process_photo(photo):
    # process a photo using exiftool
    global _args

    exif_cmd = []

    # TODO: Update to use is_missing()
    photopath = photo.path()
    if not photopath:
        print(
            "WARNING: photo %s does not appear to exist; skipping" % (photopath),
            file=sys.stderr,
        )
        return

    # get existing metadata
    j = get_exif_info_as_json(photopath)

    if _debug:
        print("json metadata for %s = %s" % (photopath, j))

    keywords = None
    persons = None

    keywords_raw = None
    persons_raw = None

    if photo.keywords():
        # merge existing keywords, removing duplicates
        tmp1 = j[0]["IPTC:Keywords"] if "IPTC:Keywords" in j[0] else None
        tmp2 = j[0]["XMP:TagsList"] if "XMP:TagsList" in j[0] else None
        keywords_raw = build_list([photo.keywords(), tmp1, tmp2])
        keywords_raw = set(keywords_raw)
        for keyword in keywords_raw:
            exif_cmd.append(f"-XMP:TagsList={keyword}")
            exif_cmd.append(f"-keywords={keyword}")

    if photo.persons():
        tmp1 = j[0]["XMP:Subject"] if "XMP:Subject" in j[0] else None
        tmp2 = j[0]["XMP:PersonInImage"] if "XMP:PersonInImage" in j[0] else None
        #        print ("photopath %s tmp1 = '%s' tmp2 = '%s'" % (photopath, tmp1, tmp2))
        persons_raw = build_list([photo.persons(), tmp1, tmp2])
        persons_raw = set(persons_raw)
        for person in persons_raw:
            exif_cmd.append(f"-xmp:PersonInImage={person}")
            exif_cmd.append(f"-subject={person}")

    # desc = desc or _dbphotos[uuid]["extendedDescription"]
    desc = photo.description()
    if desc:
        exif_cmd.append(f"-ImageDescription={desc}")
        exif_cmd.append(f"-xmp:description={desc}")

    # title = name
    title = photo.name()
    if title:
        exif_cmd.append(f"-xmp:title={title}")

    # only run exiftool if something to update
    if exif_cmd:
        if _args.inplace:
            exif_cmd.append("-overwrite_original_in_place")

        # -P = preserve timestamp
        exif_cmd.append("-P")

        # add photopath as last argument
        exif_cmd.append(photopath)
        exif_cmd.insert(0, _exiftool)
        if _debug:
            print(f"running: {exif_cmd}")

        if not _args.test:
            try:
                # SECURITY NOTE: none of the args to exiftool are shell quoted
                # as subprocess.run does this as long as shell=True is not used
                proc = subprocess.run(exif_cmd, check=True, stdout=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                sys.exit("subprocess error calling command %s %s" % (exif_cmd, e))
            else:
                if _debug:
                    print("returncode: %d" % proc.returncode)
                    print(
                        "Have {} bytes in stdout:\n{}".format(
                            len(proc.stdout), proc.stdout.decode("utf-8")
                        )
                    )
                verbose(proc.stdout.decode("utf-8"))
        else:
            tqdm.write(f"TEST: {exif_cmd}")
    else:
        verbose(f"Skipping photo {photopath}, nothing to do")

    # update xattr tags if requested
    # TODO: update to use osxmetadata
    if (_args.xattrtag and keywords_raw) or (_args.xattrperson and persons_raw):
        # xattr_cmd = "/usr/bin/xattr -w com.apple.metadata:_kMDItemUserTags "
        taglist = []
        if _args.xattrtag and keywords_raw:
            taglist = build_list([taglist, list(keywords_raw)])
        if _args.xattrperson and persons_raw:
            taglist = build_list([taglist, list(persons_raw)])

        verbose("applying extended attributes")
        # verbose("running: %s" % xattr_cmd)

        if not _args.test:
            try:
                meta = osxmetadata.OSXMetaData(photopath)
                for tag in taglist:
                    meta.tags += tag
            except Exception as e:
                sys.exit(f"Error: {e}")

    return


def main():
    global _verbose
    global _dbfile
    global _args
    global _exiftool

    _exiftool = get_exiftool_path()
    # setup_applescript()
    process_arguments()

    photosdb = None

    if not _args.force:
        # prompt user to continue
        print("Caution: This script may modify your photos library")
        # TODO: modify oxphotos to get this info as module level call
        # print("Library: %s, database: %s" % (library_path, filename))
        print(
            "It is possible this will cause irreparable damage to your Photos library"
        )
        print("Use this script at your own risk")
        ans = input("Type 'Y' to continue: ")
        if ans.upper() != "Y":
            sys.exit(0)

    if any(
        [_args.all, _args.album, _args.keyword, _args.person, _args.uuid, _args.list]
    ):
        photosdb = osxphotos.PhotosDB(dbfile=_dbfile)
    else:
        print(
            "You must select at least one of the following options: "
            + "--all, --album, --keyword, --person, --uuid"
        )
        sys.exit(0)

    if _args.list:
        if "keyword" in _args.list or "all" in _args.list:
            print("Keywords/tags (photo count): ")
            for keyword, count in photosdb.keywords_as_dict().items():
                print(f"\t{keyword} ({count})")
            print("-" * 60)

        if "person" in _args.list or "all" in _args.list:
            print("Persons (photo count): ")
            for person, count in photosdb.persons_as_dict().items():
                print(f"\t{person} ({count})")
            print("-" * 60)

        if "album" in _args.list or "all" in _args.list:
            print("Albums (photo count): ")
            for album, count in photosdb.albums_as_dict().items():
                print(f"\t{album} ({count})")
            print("-" * 60)
        sys.exit(0)

    photos = []
    # collect list of files to process
    # for now, all conditions (albums, keywords, uuid, faces) are considered "OR"
    # e.g. --keyword=family --album=Vacation finds all photos with keyword family OR album Vacation
    # todo: a lot of repetitive code here

    if _args.all:
        # process all the photos
        # photos = list(_dbphotos.keys())
        photos = photosdb.photos()
    else:
        if _args.album is not None:
            photos.extend(photosdb.photos(albums=_args.album))

        if _args.uuid is not None:
            photos.extend(photosdb.photos(uuid=_args.uuid))

        if _args.keyword is not None:
            photos.extend(photosdb.photos(keywords=_args.keyword))

        if _args.person is not None:
            photos.extend(photosdb.photos(persons=_args.person))

    if _debug:
        pp = pprint.PrettyPrinter(indent=4)
        print("Photos to process:")
        pp.pprint(photos)

    # process each photo
    if len(photos) > 0:
        tqdm.write(f"Processing {len(photos)} photo(s)")
        for photo in tqdm(iterable=photos):
            # TODO: put is_missing logic here?
            verbose(f"processing photo: {photo.filename()} {photo.path()}")
            # TODO: pass _args.test as test=
            process_photo(photo)
    else:
        tqdm.write("No photos found to process")


if __name__ == "__main__":
    main()
