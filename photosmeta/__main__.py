#!/usr/bin/env python3

# photosmeta
# Copyright (c) 2019 Rhet Turnbull <rturnbull+git@gmail.com>
#
# This script will extract known metadata from Apple's Photos library and
# write this metadata to EXIF/IPTC/XMP fields in the photo file
# For example: Photos knows about Faces (personInImage) but does not
# preserve this data when exporting the original photo

# Metadata currently extracted and where it is placed:
# Photos Faces --> XMP:PersonInImage
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
# todo: position data (lat / lon)
# todo: option to export then apply tags (e.g. don't tag original)
# todo: standardize/cleanup exception handling in helper functions
# todo: how are live photos handled
# todo: use -stay_open with exiftool to aviod repeated subprocess calls
# todo: right now, options (keyword, person, etc) are OR...add option for AND
#         e.g. only process photos in album=Test AND person=Joe
# todo: options to add:
# --exportbydate to create date folders in export folder (e.g. 2019/10/05/file.jpg, etc)
# todo: test cases:
#     1) photo edited in Photos
#     2) photo edited in external editor
#     3) photo where original in cloud but not on device (RKMaster.isMissing)
# todo: Add other xattr metadata such as kMDItemAlbum?
#   see: https://developer.apple.com/library/archive/documentation/CoreServices/Reference/MetadataAttributesRef/Reference/CommonAttrs.html#//apple_ref/doc/uid/TP40001694-SW1


import argparse
import itertools
import json
import logging
import os.path
import pathlib
import pprint
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from osxmetadata import OSXMetaData, Tag
import osxphotos
from tqdm import tqdm

from ._util import build_list, check_file_exists
from ._version import __version__

# TODO: cleanup globals to minimize number of them
# Globals
_VERBOSE = False  # print verbose output
# set _DEBUG = True to enable debug output
_DEBUG = False

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s",
)

if not _DEBUG:
    logging.disable(logging.DEBUG)


def _debug(debug):
    """ Enable or disable debug logging """
    if debug:
        logging.disable(logging.NOTSET)
    else:
        logging.disable(logging.DEBUG)


def verbose(s):
    """ print s if global _VERBOSE == True """
    if _VERBOSE:
        tqdm.write(s)


# custom argparse class to show help if error triggered
class MyParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        self.print_help()
        sys.exit(2)


def process_arguments():
    """ Process command line args, returns args in args """

    # Setup command line arguments
    parser = MyParser()
    # one required argument: path to database file
    # parser.add_argument("DATABASE_FILE", help="path to Photos database file")
    parser.add_argument(
        "photos_library",
        nargs="?",
        help="path to Photos library database, e.g. ~/Pictures/Photos\ Library.photoslibrary "
        "NOTE: May be specified either as positional argument or via --database",
    )
    parser.add_argument(
        "--database",
        help="path to Photos library database, e.g. ~/Pictures/Photos\ Library.photoslibrary "
        "NOTE: May be specified either as positional argument or via --database",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False, help="print verbose output"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        default=False,
        help="Do not prompt before processing",
    )
    parser.add_argument(
        "--debug", action="store_true", default=False, help=argparse.SUPPRESS
    )  # TODO: eventually remove this
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help="list files to be updated but do not actually udpate meta data; "
        "most useful with --verbose",
    )
    parser.add_argument(
        "--keyword", action="append", help="only process files containing keyword"
    )
    parser.add_argument(
        "--album", action="append", help="only process files contained in album"
    )
    parser.add_argument(
        "--person", action="append", help="only process files tagged with person"
    )
    parser.add_argument(
        "--uuid", action="append", help="only process file matching UUID"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="process all photos in the database",
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
        "--showmissing",
        action="store_true",
        default=False,
        help="show photos which are in the database but missing from disk. "
        "Will *not* process other photos--e.g. will not modify metadata."
        "For example, this can happen because the photo has not been downloaded from iCloud.",
    )
    parser.add_argument(
        "--noprogress",
        action="store_true",
        default=False,
        help="do not show progress bar; helpful with --verbose",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        default=False,
        help="show version number and exit",
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
        "--list=keyword, --list=album, --list=person",
    )
    parser.add_argument(
        "--export",
        help="export photos before applying metadata; set EXPORT to the export path; "
        "will leave photos in the Photos library unchanged and only add metadata to the exported photos",
    )
    parser.add_argument(
        "--export-by-date",
        action="store_true",
        default=False,
        help="Automatically create output folders to organize photos "
        "by date created (e.g. DEST/2019/12/20/photoname.jpg).",
    )
    parser.add_argument(
        "--edited",
        action="store_true",
        default=False,
        help="Also update or export edited version of photo if one exists; "
        "if exported, edited version will be named photoname_edited.ext where "
        "photoname is name of original photo and ext is extension of original photo. "
        "Warning: recommend --edited not be used with --inplace as it can cause errors when "
        "opening the photo in Photos.app",
    )
    parser.add_argument(
        "--original-name",
        action="store_true",
        default=False,
        help="Use photo's original filename instead of current filename for export",
    )
    parser.add_argument(
        "--albums-as-keywords",
        action="store_true",
        default=False,
        help="Store album names as keywords",
    )

    # if no args, show help and exit
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(0)

    args = parser.parse_args()

    return args


@lru_cache(maxsize=1)
def get_exiftool_path():
    """ return path of exiftool, cache result """
    result = subprocess.run(["which", "exiftool"], stdout=subprocess.PIPE)
    exiftool_path = result.stdout.decode("utf-8")
    logging.debug("exiftool path = %s" % (exiftool_path))
    if exiftool_path:
        return exiftool_path.rstrip()
    else:
        sys.exit(
            "Could not find exiftool. Please download and install from "
            "https://exiftool.org/"
        )


def get_exif_info_as_json(photopath):
    """ get exif info from file as JSON via exiftool """

    if not check_file_exists(photopath):
        raise ValueError("Photopath %s does not appear to be valid file" % photopath)
        return

    exiftool = get_exiftool_path()
    exif_cmd = [exiftool, "-G", "-j", "-sort", photopath]

    try:
        proc = subprocess.run(exif_cmd, check=True, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        sys.exit("subprocess error calling command %s %s: " % (exif_cmd, e))
    else:
        logging.debug("returncode: %d" % proc.returncode)
        logging.debug(
            "Have {} bytes in stdout:\n{}".format(
                len(proc.stdout), proc.stdout.decode("utf-8")
            )
        )

    j = json.loads(proc.stdout.decode("utf-8").rstrip("\r\n"))

    return j


def export_photo(
    photo, dest, verbose, export_by_date, overwrite, export_edited, original_name
):
    """ Helper function for export that does the actual export
        photo: PhotoInfo object
        dest: destination path as string
        verbose: boolean; print verbose output
        export_by_date: boolean; create export folder in form dest/YYYY/MM/DD
        overwrite: boolean; overwrite dest file if it already exists
        original_name: boolean; use original filename instead of current filename
        returns destination path of exported photo or None if photo was missing 
    """

    if photo.ismissing:
        space = " " if not verbose else ""
        tqdm.write(f"{space}Skipping missing photos {photo.filename}")
        return None
    elif not os.path.exists(photo.path):
        space = " " if not verbose else ""
        tqdm.write(
            f"{space}WARNING: file {photo.path} is missing but ismissing=False, "
            f"skipping {photo.filename}"
        )
        return None

    filename = None
    if original_name:
        filename = photo.original_filename
    else:
        filename = photo.filename

    if verbose:
        tqdm.write(f"Exporting {photo.filename} as {filename}")

    if export_by_date:
        date_created = photo.date.timetuple()
        dest = create_path_by_date(dest, date_created)

    photo_path = photo.export(dest, filename, overwrite=overwrite)[0]

    # if export-edited, also export the edited version
    # verify the photo has adjustments and valid path to avoid raising an exception
    if export_edited and photo.hasadjustments and photo.path_edited is not None:
        edited_name = pathlib.Path(pathlib.Path(photo_path).name)
        edited_name = f"{edited_name.stem}_edited{edited_name.suffix}"
        if verbose:
            tqdm.write(f"Exporting edited version of {filename} as {edited_name}")
        photo.export(dest, edited_name, overwrite=overwrite, edited=True)

    return photo_path


def process_photo(
    photo,
    test=False,
    export=None,
    inplace=False,
    xattrtag=False,
    xattrperson=False,
    export_by_date=False,
    edited=False,
    original_name=False,
    albums_as_keywords=False,
):
    """ process a photo using exiftool to write metadata to image file 
        test: run in test mode (don't actually process anything) 
        export: must be a valid path; if not None, all photos will be exported to export path before processing 
                will test to verify export is valid directory; 
                if file exists in export path, new file will be created with name filename (1).jpg, filename (2).jpg, etc 
        inplace: modify files in place (don't export) 
        xattrtag: apply keywords to extended attribute tags 
        xattrperson: apply person name to extended attribute tags 
        export_by_date: if export path is not None, will create sub-folders in export based on photo creation date
        edited: also modify (inplace) or export edited version if one exits
        original_name: use original filename instead of current filename for export 
        albums_as_keywords: treat album names as keywords """

    exif_cmd = []

    photopath = photo.path
    if photo.ismissing or not photopath or not os.path.exists(photopath):
        tqdm.write(
            f"WARNING: skipping missing photo '{photo.filename}' "
            f"(ismissing={photo.ismissing}, path='{photopath}'); skipping"
        )
        return

    # if export path set, then copy file before applying metadata
    if export:
        verbose(f"Exporting {photopath} to {export}")
        if not test:
            # photo, dest, verbose, export_by_date, overwrite, export_edited, original_name
            photopath = export_photo(
                photo, export, _VERBOSE, export_by_date, False, edited, original_name
            )

    # get existing metadata
    j = get_exif_info_as_json(photopath)

    logging.debug("json metadata for %s = %s" % (photopath, j))

    keywords = None
    persons = None

    keywords_raw = None
    persons_raw = None

    keywords_raw = set()
    if photo.keywords:
        # merge existing keywords, removing duplicates
        tmp1 = j[0]["IPTC:Keywords"] if "IPTC:Keywords" in j[0] else None
        tmp2 = j[0]["XMP:TagsList"] if "XMP:TagsList" in j[0] else None
        keywords_raw = build_list([photo.keywords, tmp1, tmp2])
        keywords_raw = set(keywords_raw)
        for keyword in keywords_raw:
            exif_cmd.append(f"-XMP:TagsList={keyword}")
            exif_cmd.append(f"-keywords={keyword}")

    # process albums as keywords if requested
    # don't process any album names that have already been processed as keywords
    if albums_as_keywords:
        for album in photo.albums:
            if album not in keywords_raw:
                exif_cmd.append(f"-XMP:TagsList={album}")
                exif_cmd.append(f"-keywords={album}")

    if photo.persons:
        # tmp1 = j[0]["XMP:Subject"] if "XMP:Subject" in j[0] else None
        tmp2 = j[0]["XMP:PersonInImage"] if "XMP:PersonInImage" in j[0] else None
        #        print ("photopath %s tmp1 = '%s' tmp2 = '%s'" % (photopath, tmp1, tmp2))
        # persons_raw = build_list([photo.persons, tmp1, tmp2])
        persons_raw = build_list([photo.persons, tmp2])
        persons_raw = set(persons_raw)

        # Photos 5 identifies all faces even if unknown, remove these
        if osxphotos._constants._UNKNOWN_PERSON in persons_raw:
            persons_raw.remove(osxphotos._constants._UNKNOWN_PERSON)

        for person in persons_raw:
            exif_cmd.append(f"-xmp:PersonInImage={person}")
            # exif_cmd.append(f"-subject={person}")

    # desc = desc or _dbphotos[uuid]["extendedDescription"]
    desc = photo.description
    if desc:
        exif_cmd.append(f"-ImageDescription={desc}")
        exif_cmd.append(f"-xmp:description={desc}")

    # title = name
    title = photo.title
    if title:
        exif_cmd.append(f"-xmp:title={title}")

    # only run exiftool if something to update
    if exif_cmd:
        paths = [photopath]
        # if edited, also process the edited version
        if edited and photo.hasadjustments:
            if export:
                edited_path = pathlib.Path(photopath)
                edited_name = f"{edited_path.stem}_edited{edited_path.suffix}"
                edited_path = pathlib.Path(photopath).parent / pathlib.Path(edited_name)
                if os.path.exists(edited_path):
                    paths.append(str(edited_path))
                else:
                    tqdm.write(
                        f"WARNING: skipping file {str(edited_path)}, does not appear to exist"
                    )
            else:
                paths.append(photo.path_edited)

        if inplace or export:
            exif_cmd.append("-overwrite_original_in_place")

        # -P = preserve timestamp
        exif_cmd.append("-P")

        # add photopath as last argument
        exiftool = get_exiftool_path()
        exif_cmd.insert(0, exiftool)
        for photopath in paths:
            # process both original and edited if requested
            logging.debug(f"running: {[*exif_cmd,photopath]}")

            if not test:
                try:
                    # SECURITY NOTE: none of the args to exiftool are shell quoted
                    # as subprocess.run does this as long as shell=True is not used
                    proc = subprocess.run(
                        [*exif_cmd, photopath], check=True, stdout=subprocess.PIPE
                    )
                except subprocess.CalledProcessError as e:
                    sys.exit("subprocess error calling command %s %s" % (exif_cmd, e))
                else:
                    logging.debug("returncode: %d" % proc.returncode)
                    logging.debug(
                        "Have {} bytes in stdout:\n{}".format(
                            len(proc.stdout), proc.stdout.decode("utf-8")
                        )
                    )
                    verbose(proc.stdout.decode("utf-8"))
            else:
                verbose(f"TEST: Processed {photo.filename}")
                logging.debug(f"TEST: {[*exif_cmd, photopath]}")

            # update xattr tags if requested
            if (xattrtag and keywords_raw) or (xattrperson and persons_raw):
                taglist = []
                if xattrtag and keywords_raw:
                    taglist = build_list([taglist, list(keywords_raw)])
                if xattrperson and persons_raw:
                    taglist = build_list([taglist, list(persons_raw)])

                verbose(f"Applying extended attributes to {photopath}")

                if not test:
                    try:
                        meta = OSXMetaData(photopath)
                        for tag in taglist:
                            meta.tags += [Tag(tag)]
                    except Exception as e:
                        raise e
                else:
                    verbose(f"TEST: applied extended attributes to {photopath}")
    else:
        verbose(f"Skipping photo {photopath}, nothing to do")

    return


def create_path_by_date(dest, dt):
    """ Creates a path in dest folder in form dest/YYYY/MM/DD/
        dest: valid path as str
        dt: datetime.timetuple() object
        Checks to see if path exists, if it does, do nothing and return path
        If path does not exist, creates it and returns path"""
    if not os.path.isdir(dest):
        raise FileNotFoundError(f"dest {dest} must be valid path")
    yyyy, mm, dd = dt[0:3]
    yyyy = str(yyyy).zfill(4)
    mm = str(mm).zfill(2)
    dd = str(dd).zfill(2)
    new_dest = os.path.join(dest, yyyy, mm, dd)
    if not os.path.isdir(new_dest):
        os.makedirs(new_dest)
    return new_dest


def main():
    """ main function for the script """
    """ globals: _VERBOSE (print verbose output) """
    """ processes arguments, loads the Photos database, """
    """ finds matching photos, then processes each one """
    global _VERBOSE

    args = process_arguments()
    if args.verbose:
        _VERBOSE = True

    if args.debug:
        _debug(True)

    if args.version:
        print(f"Version: {__version__}")
        sys.exit(0)

    if args.export:
        # verify export path is valid
        if not os.path.isdir(args.export):
            sys.exit(f"export path {args.export} must be valid path")

    # Will hold the OSXPhotos.PhotoDB object
    photosdb = None

    if not args.force:
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

    if any([args.all, args.album, args.keyword, args.person, args.uuid, args.list]):
        print("Loading database...")
        db = args.photos_library if args.photos_library is not None else args.database
        if db is None or not os.path.exists(db):
            sys.exit(
                "Must pass valid Photos library database via --database or photos_library positional argument"
            )
        photosdb = osxphotos.PhotosDB(dbfile=db)
        print(f"Loaded database {photosdb.library_path}")
    else:
        print(
            "You must select at least one of the following options: "
            + "--all, --album, --keyword, --person, --uuid"
        )
        sys.exit(0)

    if args.list:
        if "keyword" in args.list or "all" in args.list:
            print("Keywords/tags (photo count): ")
            for keyword, count in photosdb.keywords_as_dict.items():
                print(f"\t{keyword} ({count})")
            print("-" * 60)

        if "person" in args.list or "all" in args.list:
            print("Persons (photo count): ")
            for person, count in photosdb.persons_as_dict.items():
                print(f"\t{person} ({count})")
            print("-" * 60)

        if "album" in args.list or "all" in args.list:
            print("Albums (photo count): ")
            for album, count in photosdb.albums_as_dict.items():
                print(f"\t{album} ({count})")
            print("-" * 60)
        sys.exit(0)

    # collect list of files to process
    # for now, all conditions (albums, keywords, uuid, faces) are considered "OR"
    # e.g. --keyword=family --album=Vacation finds all photos with keyword family OR album Vacation
    photos = []

    if args.all:
        # process all the photos
        photos = photosdb.photos()
    else:
        if args.album is not None:
            photos.extend(photosdb.photos(albums=args.album))

        if args.uuid is not None:
            photos.extend(photosdb.photos(uuid=args.uuid))

        if args.keyword is not None:
            photos.extend(photosdb.photos(keywords=args.keyword))

        if args.person is not None:
            photos.extend(photosdb.photos(persons=args.person))

    if _DEBUG:
        pp = pprint.PrettyPrinter(indent=4)
        logging.debug("Photos to process:")
        logging.debug(pp.pformat(photos))

    # process each photo
    # if showmissing=True, only list missing photos, don't process them
    if len(photos) > 0:
        tqdm.write(f"Processing {len(photos)} photo(s)")
        for photo in tqdm(iterable=photos, disable=args.noprogress):
            verbose(f"processing photo: {photo.filename} {photo.path}")
            if photo.ismissing and args.showmissing:
                tqdm.write(
                    f"Missing photo: '{photo.filename}' in database but ismissing flag set; path: {photo.path}"
                )
            elif not args.showmissing:
                process_photo(
                    photo,
                    test=args.test,
                    export=args.export,
                    inplace=args.inplace,
                    xattrtag=args.xattrtag,
                    xattrperson=args.xattrperson,
                    export_by_date=args.export_by_date,
                    edited=args.edited,
                    original_name=args.original_name,
                    albums_as_keywords=args.albums_as_keywords,
                )
    else:
        tqdm.write("No photos found to process")


if __name__ == "__main__":
    main()
