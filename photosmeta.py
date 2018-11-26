#!/usr/bin/env python3

# photosmeta
# Copyright (c) 2018 Rhet Turnbull <rturnbull+git@gmail.com>
#
# Version 0.1
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

# Optionally, will write keywords and/or faces (persons) to 
#   Mac OS native keywords (xattr kMDItemUserTags)

# Dependencies:
#   exiftool by Phil Harvey: 
#       https://www.sno.phy.queensu.ca/~phil/exiftool/

# This code was inspired by photo-export by Patrick Fältström see:
#   https://github.com/patrikhson/photo-export
#   Copyright (c) 2015 Patrik Fältström <paf@frobbit.se>

# See also:
#    https://github.com/orangeturtle739/photos-export
#    https://github.com/guinslym/pyexifinfo/tree/master/pyexifinfo

# NOTE: This is my very first python project. Using this script might
# completely destroy your Photos library.  You have been warned! :-)

# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# ## THINGS TODO ###
# todo: progress bar for photos to process
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



import sys
import os
import re
import pprint
import plistlib
import sqlite3
from datetime import datetime
import time
import subprocess
import os.path
import argparse
from pathlib import Path
import objc
from Foundation import *
import CoreFoundation
import urllib.parse
import applescript
from plistlib import load 
from shutil import copyfile
import tempfile
import json

# Globals
_debug = False
_exiftool = None  # will hold path to exiftools
_args = None #command line args as processed by argparse
_verbose = False  #print verbose output 
_dbfile = None #will hold path to the Photos sqlite3 database file

# Dict with information about all photos by uuid
_dbphotos = {}

# Dict with information about all persons/photos by uuid
_dbfaces_uuid = {}

# Dict with information about all persons/photos by person
_dbfaces_person = {}

# Dict with information about all keywords/photos by uuid
_dbkeywords_uuid = {}

# Dict with information about all keywords/photos by keyword
_dbkeywords_keyword = {}

# Dict with information about all albums/photos by uuid
_dbalbums_uuid = {}

# Dict with information about all albums/photos by album
_dbalbums_album = {}

# Dict with information about all the volumes/photos by uuid
_dbvolumes = {}

#AppleScript calls that will be created by setup_applescript()
scpt_export = ""
scpt_launch = ""
scpt_quit = ""

#TODO: used by scpt_export--remove
tmppath = "%s/tmp/" % str(Path.home())

#custom argparse class to show help if error triggered
class MyParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write('error: %s\n' % message)
        self.print_help()
        sys.exit(2)
#class MyParser(argparse.ArgumentParser):

def process_arguments():
    global _args
    global _verbose
    global _dbfile
    global _debug

    # Setup command line arguments
    parser = MyParser()
    # one required argument: path to database file
    #parser.add_argument("DATABASE_FILE", help="path to Photos database file")
    parser.add_argument("--database",
                        help="database file [will default to Photos default file]")
    parser.add_argument("-v", "--verbose", action="store_true", default=False,
                        help="print verbose output",)
    parser.add_argument("-f", "--force", action="store_true", default=False,
                        help="Do not prompt before processing",)
    parser.add_argument("--debug", action="store_true", default=False,
                        help="enable debug output",) #TODO: eventually remove this
    parser.add_argument("--test", action="store_true", default=False,
                        help="list files to be updated but do not actually udpate meta data",)
    parser.add_argument("--keyword", action='append',
                        help="only process files containing keyword")
    parser.add_argument("--album", action='append',
                        help="only process files contained in album")
    parser.add_argument("--person", action='append',
                        help="only process files         tagged with person")
    parser.add_argument("--uuid", action='append',
                        help="only process file matching UUID")
    parser.add_argument("--all", action='store_true', default=False,
                        help="export all photos in the database")
    parser.add_argument("--inplace", action='store_true', default=False,
                        help="modify all photos in place (don't create backups)")
    parser.add_argument("--xattrtag", action='store_true', default=False,
                        help="write tags/keywords to file's extended attributes (kMDItemUserTags) " \
                            "so you can search in spotlight using 'tag:' " \
                            "May be combined with -xattrperson " \
                            "CAUTION: this overwrites all existing kMDItemUserTags (to be fixed in future release)")
    parser.add_argument("--xattrperson", action='store_true', default=False,
                        help="write person (faces) to file's extended attributes (kMDItemUserTags) " \
                        "so you can search in spotlight using 'tag:' " \
                        "May be combined with --xattrtag " \
                        "CAUTION: this overwrites all existing kMDItemUserTags (to be fixed in future release)")

    parser.add_argument("--list", action='append',
                        help="list keywords, albums, persons found in database: " +
                        "--list=keyword, --list=album, --list=person")

    #if no args, show help and exit
    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    _args = parser.parse_args()
    _verbose = _args.verbose
    _dbfile = _args.database
    _debug = _args.debug

    if _args.keyword is not None:
        print("keywords: " + " ".join(_args.keyword))
#process_arguments

def check_file_exists(filename):
    #returns true if file exists and is not a directory
    #otherwise returns false
    
    filename = os.path.abspath(filename)
    return (os.path.exists(filename) and not os.path.isdir(filename))
#check_file_exists


def get_photos_library_path():
    #return the path to the Photos library
    plist_file = Path(str(Path.home()) + 
        "/Library/Containers/com.apple.Photos/Data/Library/Preferences/com.apple.Photos.plist")
    if plist_file.is_file():
        with open(plist_file, 'rb') as fp:
            pl = load(fp)
    else:
        print('could not find plist file: ' + str(plist_file),file=sys.stderr)
        return None

    #get the IPXDefaultLibraryURLBookmark from com.apple.Photos.plist
    #this is a serialized CFData object
    photosurlref = pl["IPXDefaultLibraryURLBookmark"]

    if photosurlref != None:
        #use CFURLCreateByResolvingBookmarkData to de-serialize bookmark data into a CFURLRef
        photosurl = CoreFoundation.CFURLCreateByResolvingBookmarkData(
                kCFAllocatorDefault, photosurlref, 0, None, None, None, None)

        #the CFURLRef we got is a sruct that python treats as an array
        #I'd like to pass this to CFURLGetFileSystemRepresentation to get the path but
        #CFURLGetFileSystemRepresentation barfs when it gets an array from python instead of expected struct
        #first element is the path string in form: 
        #file:///Users/username/Pictures/Photos%20Library.photoslibrary/
        photosurlstr = photosurl[0].absoluteString() if photosurl[0] else None
        
        #now coerce the file URI back into an OS path
        #surely there must be a better way
        if photosurlstr is not None:
            photospath = os.path.normpath(
                    urllib.parse.unquote(
                    urllib.parse.urlparse(
                    photosurlstr)
                    .path))
        else:
            print("Could not extract photos URL String from IPXDefaultLibraryURLBookmark",file=sys.stderr)
            return None

        return photospath
    else:
        print("Could not get path to Photos database",file=sys.stderr)
        return None
#get_photos_library_path

def copy_db_file(fname):
    #copies the sqlite database file to a temp file
    #returns the name of the temp file
    #required because python's sqlite3 implementation can't read a locked file
    fd, tmp = tempfile.mkstemp(suffix=".db",prefix="photos")
    verbose("copying " + fname +" to " + tmp)
    try:
        copyfile(fname,tmp)
    except:
        print("copying " + fname +" to " + tmp,file=sys.stderr)
        sys.exit()
    return tmp
#copy_db_file

# Handle progress bar (equivalent)
# TODO: this code from https://github.com/patrikhson/photo-export
#       it's not 
# TODO: replace this code with https://pypi.org/project/progress/
_pbar_status_text = ""
_pbar_maxvalue = -1

def init_pbar_status(text, max):
    global _pbar_status_text
    global _pbar_maxvalue
    print("init: %s %s" % (text, max))
    _pbar_status_text = text
    _pbar_maxvalue = max
#init_pbar_status

def set_pbar_status(value):
    global _pbar_status_text
    global _pbar_maxvalue
    if(not _verbose):
        if(_pbar_maxvalue > 0):
            progress = value / _pbar_maxvalue
            sys.stdout.write('\r%s: [ %-30s ] %3d%%' % (
                _pbar_status_text, format('#' * int(progress * 30)), int(progress * 100)))
        else:
            #todo: this will produce an error theNum not defined
            sys.stdout.write('\r%s' % (_pbar_status_text))
        sys.stdout.flush()
#set_pbar_status

def close_pbar_status():
    global _pbar_status_text
    global _pbar_maxvalue
    if(not _verbose):
        sys.stdout.write('\r%s: [ %-30s ] %3d%%\n' %
                         (_pbar_status_text, format('#' * 30), 100))
    _pbar_maxvalue = -1
    _pbar_status_text = ""
#close_pbar_status

# Various AppleScripts we need
def setup_applescript():
    global scpt_export
    global scpt_launch
    global scpt_quit

    # Compile apple script that exports one image
    scpt_export = applescript.AppleScript('''
        on run {arg}
          set thepath to "%s"
          tell application "Photos"
            set theitem to media item id arg
            set thelist to {theitem}
            export thelist to POSIX file thepath
          end tell
        end run
        ''' % (tmppath))

    # Compile apple script that launches Photos.App
    scpt_launch = applescript.AppleScript('''
        on run
          tell application "Photos"
            activate
          end tell
        end run
        ''')

    # Compile apple script that quits Photos.App
    scpt_quit = applescript.AppleScript('''
        on run
          tell application "Photos"
            quit
          end tell
        end run
        ''')
#setup_applescript

def verbose(s):
    #print output only if global _verbose is True
    if(_verbose):
        print(s)
#verbose

def open_sql_file(file):
    fname = file
    verbose("Trying to open database %s" % (fname))
    try:
        conn = sqlite3.connect("%s" % (fname))
        c = conn.cursor()
    except sqlite3.Error as e:
        print("An error occurred: %s %s" % (e.args[0], fname))
        sys.exit(3)
    verbose("SQLite database is open")
    return(conn, c)
#open_sql_file

def get_exiftool_path():
    global _exiftool
    result = subprocess.run(['which', 'exiftool'], stdout=subprocess.PIPE)
    exiftool_path = result.stdout.decode('utf-8')
    verbose("exiftool path = %s" % (exiftool_path))
    if exiftool_path is not "":
        return exiftool_path.rstrip()
    else:
        errstr = "Could not find exiftool"
        sys.exit(errstr)
#get_exiftool_path

def process_database(fname):
    global _dbphotos
    global _dbfaces_uuid
    global _dbfaces_person
    global _dbkeywords_uuid
    global _dbkeywords_keyword
    global _dbalbums_uuid
    global _dbalbums_album
    global _debug

    # Epoch is Jan 1, 2001
    td = (datetime(2001, 1, 1, 0, 0) - datetime(1970, 1, 1, 0, 0)).total_seconds()

    # Ensure Photos.App is not running
    scpt_quit.run()

    tmp_db = copy_db_file(fname)
    (conn, c) = open_sql_file(tmp_db)
    verbose("Have connection with database")

    # Look for all combinations of persons and pictures
    verbose("Getting information about persons")

    i = 0
    c.execute(
        "select count(*) from RKFace, RKPerson where RKFace.personID = RKperson.modelID")
    init_pbar_status("Faces", c.fetchone()[0])
    # c.execute("select RKPerson.name, RKFace.imageID from RKFace, RKPerson where RKFace.personID = RKperson.modelID")
    c.execute("select RKPerson.name, RKVersion.uuid from RKFace, RKPerson, RKVersion, RKMaster "
            + "where RKFace.personID = RKperson.modelID and RKVersion.modelId = RKFace.ImageModelId "
            + "and RKVersion.type = 2 and RKVersion.masterUuid = RKMaster.uuid and "
            + "RKVersion.filename not like '%.pdf'")
    for person in c:
        if person[0] == None:
            verbose("skipping person = None %s" % person[1])
            continue
        if not person[1] in _dbfaces_uuid:
            _dbfaces_uuid[person[1]] = []
        if not person[0] in _dbfaces_person:
            _dbfaces_person[person[0]] = []
        _dbfaces_uuid[person[1]].append(person[0])
        _dbfaces_person[person[0]].append(person[1])
        set_pbar_status(i)
        i = i + 1
    verbose("Finished walking through persons")
    close_pbar_status()

    verbose("Getting information about albums")
    i = 0
    c.execute("select count(*) from RKAlbum, RKVersion, RKAlbumVersion where "
            + "RKAlbum.modelID = RKAlbumVersion.albumId and "
            + "RKAlbumVersion.versionID = RKVersion.modelId and "
            + "RKVersion.filename not like '%.pdf' and RKVersion.isInTrash = 0")
    init_pbar_status("Albums", c.fetchone()[0])
    # c.execute("select RKPerson.name, RKFace.imageID from RKFace, RKPerson where RKFace.personID = RKperson.modelID")
    c.execute("select RKAlbum.name, RKVersion.uuid from RKAlbum, RKVersion, RKAlbumVersion "
            + "where RKAlbum.modelID = RKAlbumVersion.albumId and "
            + "RKAlbumVersion.versionID = RKVersion.modelId and RKVersion.type = 2 and "
            + "RKVersion.filename not like '%.pdf' and RKVersion.isInTrash = 0")
    for album in c:
        # store by uuid in _dbalbums_uuid and by album in _dbalbums_album
        if not album[1] in _dbalbums_uuid:
            _dbalbums_uuid[album[1]] = []
        if not album[0] in _dbalbums_album:
            _dbalbums_album[album[0]] = []
        _dbalbums_uuid[album[1]].append(album[0])
        _dbalbums_album[album[0]].append(album[1])
        verbose("%s %s" % (album[1], album[0]))
        set_pbar_status(i)
        i = i + 1
    verbose("Finished walking through albums")
    close_pbar_status()

    verbose("Getting information about keywords")
    c.execute("select count(*) from RKKeyword, RKKeywordForVersion,RKVersion, RKMaster "
              + "where RKKeyword.modelId = RKKeyWordForVersion.keywordID and "
              + "RKVersion.modelID = RKKeywordForVersion.versionID and RKMaster.uuid = "
              + "RKVersion.masterUuid and RKVersion.filename not like '%.pdf' and RKVersion.isInTrash = 0")
    init_pbar_status("Keywords", c.fetchone()[0])
    c.execute("select RKKeyword.name, RKVersion.uuid, RKMaster.uuid from "
              + "RKKeyword, RKKeywordForVersion, RKVersion, RKMaster "
              + "where RKKeyword.modelId = RKKeyWordForVersion.keywordID and "
              + "RKVersion.modelID = RKKeywordForVersion.versionID "
              + "and RKMaster.uuid = RKVersion.masterUuid and RKVersion.type = 2 "
              + "and RKVersion.filename not like '%.pdf' and RKVersion.isInTrash = 0")
    i = 0
    for keyword in c:
        if not keyword[1] in _dbkeywords_uuid:
            _dbkeywords_uuid[keyword[1]] = []
        if not keyword[0] in _dbkeywords_keyword:
            _dbkeywords_keyword[keyword[0]] = []
        _dbkeywords_uuid[keyword[1]].append(keyword[0])
        _dbkeywords_keyword[keyword[0]].append(keyword[1])
        verbose("%s %s" % (keyword[1], keyword[0]))
        set_pbar_status(i)
        i = i + 1
    verbose("Finished walking through keywords")
    close_pbar_status()

    verbose("Getting information about volumes")
    c.execute("select count(*) from RKVolume")
    init_pbar_status("Volumes", c.fetchone()[0])
    c.execute("select RKVolume.modelId, RKVolume.name from RKVolume")
    i = 0
    for vol in c:
        _dbvolumes[vol[0]] = vol[1]
        verbose("%s %s" % (vol[0], vol[1]))
        set_pbar_status(i)
        i = i + 1
    verbose("Finished walking through volumes")
    close_pbar_status()

    verbose("Getting information about photos")
    c.execute("select count(*) from RKVersion, RKMaster where RKVersion.isInTrash = 0 and " 
            + "RKVersion.type = 2 and RKVersion.masterUuid = RKMaster.uuid and "
            + "RKVersion.filename not like '%.pdf'")
    init_pbar_status("Photos", c.fetchone()[0])
    c.execute("select RKVersion.uuid, RKVersion.modelId, RKVersion.masterUuid, RKVersion.filename, "
            + "RKVersion.lastmodifieddate, RKVersion.imageDate, RKVersion.mainRating, "
            + "RKVersion.hasAdjustments, RKVersion.hasKeywords, RKVersion.imageTimeZoneOffsetSeconds, "
            + "RKMaster.volumeId, RKMaster.imagePath, RKVersion.extendedDescription, RKVersion.name, "
            + "RKMaster.isMissing "
            + "from RKVersion, RKMaster where RKVersion.isInTrash = 0 and RKVersion.type = 2 and "
            + "RKVersion.masterUuid = RKMaster.uuid and RKVersion.filename not like '%.pdf'")
    i = 0
    for row in c:
        set_pbar_status(i)
        i = i + 1
        uuid = row[0]
        if _debug:
            print("i = %d, uuid = '%s, master = '%s" % (i, uuid, row[2]))
        _dbphotos[uuid] = {}
        _dbphotos[uuid]['modelID'] = row[1]
        _dbphotos[uuid]['masterUuid'] = row[2]
        _dbphotos[uuid]['filename'] = row[3]
        try:
            _dbphotos[uuid]['lastmodifieddate'] = datetime.fromtimestamp(
                row[4] + td)
        except:
            _dbphotos[uuid]['lastmodifieddate'] = datetime.fromtimestamp(
                row[5] + td)
        _dbphotos[uuid]['imageDate'] = datetime.fromtimestamp(row[5] + td)
        _dbphotos[uuid]['mainRating'] = row[6]
        _dbphotos[uuid]['hasAdjustments'] = row[7]
        _dbphotos[uuid]['hasKeywords'] = row[8]
        _dbphotos[uuid]['imageTimeZoneOffsetSeconds'] = row[9]
        _dbphotos[uuid]['volumeId'] = row[10]
        _dbphotos[uuid]['imagePath'] = row[11]
        _dbphotos[uuid]['extendedDescription'] = row[12]
        _dbphotos[uuid]['name'] = row[13]
        _dbphotos[uuid]['isMissing'] = row[14]
        verbose("Fetching data for photo %d %s %s %s %s %s: %s" %
              (i, uuid, _dbphotos[uuid]['masterUuid'], _dbphotos[uuid]['volumeId'], 
              _dbphotos[uuid]['filename'], _dbphotos[uuid]['extendedDescription'], 
              _dbphotos[uuid]['imageDate']))

    close_pbar_status()
    conn.close()

    # add faces and keywords to photo data
    for uuid in _dbphotos:
        # keywords
        if _dbphotos[uuid]['hasKeywords'] == 1:
            _dbphotos[uuid]['keywords'] = _dbkeywords_uuid[uuid]
        else:
            _dbphotos[uuid]['keywords'] = []

        if uuid in _dbfaces_uuid:
            _dbphotos[uuid]['hasPersons'] = 1
            _dbphotos[uuid]['persons'] = _dbfaces_uuid[uuid]
        else:
            _dbphotos[uuid]['hasPersons'] = 0
            _dbphotos[uuid]['persons'] = []

        if uuid in _dbalbums_uuid:
            _dbphotos[uuid]['albums'] = _dbalbums_uuid[uuid]
            _dbphotos[uuid]['hasAlbums'] = 1
        else:
            _dbphotos[uuid]['albums'] = []
            _dbphotos[uuid]['hasAlbums'] = 0

        if _dbphotos[uuid]['volumeId'] is not None:
            _dbphotos[uuid]['volume'] = _dbvolumes[_dbphotos[uuid]['volumeId']]
        else:
            _dbphotos[uuid]['volume'] = None

    #remove temporary copy of the databse
    try:
        verbose("Removing temporary databse file" + tmp_db)
        os.remove(tmp_db)
    except:
        print("Could not remove temporary database: " + tmp_db,file=sys.stderr)

    if _debug:
        pp = pprint.PrettyPrinter(indent=4)
        print("Faces:")
        pp.pprint(_dbfaces_uuid)

        print("Keywords by uuid:")
        pp.pprint(_dbkeywords_uuid)

        print("Keywords by keyword:")
        pp.pprint(_dbkeywords_keyword)

        print("Albums by uuid:")
        pp.pprint(_dbalbums_uuid)

        print("Albums by album:")
        pp.pprint(_dbalbums_album)

        print("Volumes:")
        pp.pprint(_dbvolumes)

        print("Photos:")
        pp.pprint(_dbphotos)
#process_database

def get_exif_info_as_json(photopath):
    #get exif info from file as JSON via exiftool

    if not check_file_exists(photopath):
        raise ValueError("Photopath %s does not appear to be valid file" % photopath)
        return

    _exiftool = get_exiftool_path()
    exif_cmd = "%s %s %s %s '%s'" % (_exiftool, '-G', '-j', '-sort', photopath)

    try:
        proc = subprocess.run(exif_cmd, check=True, shell=True, 
                            stdout=subprocess.PIPE) 
    except subprocess.CalledProcessError as e:
        sys.exit("subprocess error calling command %s %s: " % (exif_cmd, e))
    else:
        if _debug:
            print('returncode: %d' % proc.returncode)
            print('Have {} bytes in stdout:\n{}'.format(
                len(proc.stdout),
                proc.stdout.decode('utf-8')))

    j = json.loads(proc.stdout.decode('utf-8').rstrip('\r\n'))

    return j
#get_exif_info_as_json

def build_list(lst):
    #takes an array of elements that may be a string or list
    #  and returns a list of all items appended
    tmplst = []
    for x in lst:
        if x is not None:
            if isinstance(x, list):
                tmplst = tmplst + x
            else:
                tmplst.append(x)
    return tmplst
#build_list

def process_photo(uuid, photopath):
    #process a photo using exiftool
    global _args
    global _dbphotos

    if not check_file_exists(photopath):
        print("WARNING: photo %s does not appear to exist; skipping" % (photopath), file=sys.stderr)
        return
    
    #get existing metadata
    j = get_exif_info_as_json(photopath)
    
    if _debug:
        print("json metadata for %s = %s" % (photopath, j))

    keywords = None
    persons = None

    keywords_raw = None
    persons_raw = None

    if uuid in _dbkeywords_uuid:
        #merge existing keywords, removing duplicates
        tmp1 = j[0]['IPTC:Keywords'] if 'IPTC:Keywords' in j[0] else None
        tmp2 = j[0]['XMP:TagsList'] if 'XMP:TagsList' in j[0] else None
        keywords_raw = build_list([_dbkeywords_uuid[uuid],tmp1, tmp2])
        keywords_raw = set(keywords_raw)       
        keywords = [ "-XMP:TagsList='%s' -keywords='%s'" % (x, x) for x in keywords_raw ]
        
    if uuid in _dbfaces_uuid:
        tmp1 = j[0]['XMP:Subject'] if 'XMP:Subject' in j[0] else None
        tmp2 = j[0]['XMP:PersonInImage'] if 'XMP:PersonInImage' in j[0] else None
#        print ("photopath %s tmp1 = '%s' tmp2 = '%s'" % (photopath, tmp1, tmp2))
        persons_raw = build_list([_dbfaces_uuid[uuid],tmp1, tmp2])
        persons_raw = set(persons_raw)
        persons =  [ "-xmp:PersonInImage='%s' -subject='%s'" % (x, x) for x in persons_raw ]

    k = ''
    p = ''
    if keywords:
        k = ' '.join(keywords)
    if persons:
        p = ' '.join(persons)

    desc = ''
    desc = desc or _dbphotos[uuid]['extendedDescription']
    d = ''
    if desc:
        d = "-ImageDescription='%s' -xmp:description='%s'" % (desc, desc)

    #title = name
    title = ''
    title = title or _dbphotos[uuid]['name']
    t = ''
    if title:
        t = "-xmp:title='%s'" % (title)

    #todo: if nothing to do then skip
    
    inplace = ''
    if _args.inplace:
        inplace = "-overwrite_original_in_place"

    #print("INPLACE: %s" % inplace)

    #-P = preserve timestamp
    #todo: check to see if there's any reason to run exiftool (e.g. do nothing if k, p, d, t all none)
    exif_cmd = "%s %s %s %s %s %s -P '%s'" % (_exiftool, k, p, d, t, inplace, photopath)

    verbose("running: %s" % (exif_cmd)) 
    
    if not _args.test:
        try:
            #[_exiftool, k, p, d, t, inplace, photopath]
            proc = subprocess.run(exif_cmd, check=True, shell=True, 
                                stdout=subprocess.PIPE) 
        except subprocess.CalledProcessError as e:
            sys.exit("subprocess error calling command %s %s" % (exif_cmd, e))
        else:
            if _debug:
                print('returncode: %d' % proc.returncode)
                print('Have {} bytes in stdout:\n{}'.format(
                    len(proc.stdout),
                    proc.stdout.decode('utf-8')))
            verbose(proc.stdout.decode('utf-8')) 

    #update xattr tags if requested
    xattr_cmd = None
    if (_args.xattrtag and keywords_raw) or (_args.xattrperson and persons_raw):
        xattr_cmd = 'xattr -w com.apple.metadata:_kMDItemUserTags '
        taglist = []
        if _args.xattrtag and keywords_raw:
            taglist = build_list([taglist, list(keywords_raw)])
        if _args.xattrperson and persons_raw:
            taglist = build_list([taglist, list(persons_raw)])
        tags = ["<string>%s</string>" % (x) for x in taglist]
        plist = '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"' \
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0">' \
                '<array>%s</array></plist>' % ' '.join(tags) 

        xattr_cmd = "%s '%s' '%s'" % (xattr_cmd, plist, photopath)

        print("applying extended attributes")
        if _debug:
            print("xattr_cmd: %s" % xattr_cmd)

        if  not _args.test:
            try:
                proc = subprocess.run(xattr_cmd, check=True, shell=True, 
                                        stdout=subprocess.PIPE) 
            except subprocess.CalledProcessError as e:
                sys.exit("subprocess error calling command %s %s" % (xattr_cmd, e))
            else:
                if _debug:
                    print('returncode: %d' % proc.returncode)
                    print('Have {} bytes in stdout:\n{}'.format(
                        len(proc.stdout),
                        proc.stdout.decode('utf-8')))
        
    return
#process_photo

def main():
    global _verbose
    global _dbfile
    global _args
    global _exiftool

    _exiftool = get_exiftool_path()
    setup_applescript()
    process_arguments()

    # filename = ("%s/Pictures/Photos Library.photoslibrary" % os.path.expanduser("~"))
    print(_dbfile)
    if _dbfile is None:
        library_path = get_photos_library_path()
        print("library_path: " + library_path)
        #TODO: verify library path not None
        _dbfile = os.path.join(library_path, "database/photos.db")
        print(_dbfile)
 
    filename = _dbfile
    verbose("filename = %s" % filename)

    #TODO: replace os.path with pathlib
    #TODO: clean this up -- we'll already know library_path
    library_path = os.path.dirname(filename)
    (library_path, tmp) = os.path.split(library_path)
    masters_path = os.path.join(library_path, "Masters")
    verbose("library = %s, masters = %s" % (library_path, masters_path))

    if (not check_file_exists(filename)):
        sys.exit("_dbfile %s does not exist" % (filename))
    
    verbose("databse filename = %s" % filename)

    if not _args.force:
        #prompt user to continue
        print("Caution: This script will modify your photos library")
        print("Library: %s, database: %s" % (library_path, filename))
        print("It is possible this will cause irreparable damage to your Photos library")
        print("Use this script at your own risk")
        ans = input("Type 'Y' to continue: ")
        if ans.upper() != 'Y':
            sys.exit(0)

    if any([_args.all, _args.album, _args.keyword, _args.person, _args.uuid]):
        process_database(filename)
    else:
        print("database = " + filename)
        print("You must select at least one of the following options: " +
              "--all, --album, --keyword, --person, --uuid")
        sys.exit(0)

    if _args.list:
        if "keyword" in _args.list or "all" in _args.list   :
            print("Keywords/tags: ")
            for keyword in _dbkeywords_keyword:
                print("\t%s" % keyword)
            print("-"*60)

        if "person" in _args.list or "all" in _args.list:
            print("Persons: ")
            for person in _dbfaces_person:
                print("\t%s" % person)
            print("-"*60)

        if "album" in _args.list or "all" in _args.list:
            print("Albums: ")
            for album in _dbalbums_album:
                print("\t%s" % album)
            print("-"*60)

    photos = []
    # collect list of files to process
    # for now, all conditions (albums, keywords, uuid, faces) are considered "OR"
    # e.g. --keyword=family --album=Vacation finds all photos with keyword family OR album Vacation
    # todo: a lot of repetitive code here

    if _args.all:
        #process all the photos
        photos = list(_dbphotos.keys())
    else:
        if _args.album is not None:
            for album in _args.album:
                print("album=%s" % album)
                if album in _dbalbums_album:
                    print("processing album %s:" % album)
                    photos.extend(_dbalbums_album[album])
                else:
                    print("Could not find album '%s' in database" %
                        (album), file=sys.stderr)

        if _args.uuid is not None:
            for uuid in _args.uuid:
                print("uuid=%s" % uuid)
                if uuid in _dbphotos:
                    print("processing uuid %s:" % uuid)
                    photos.extend([uuid])
                else:
                    print("Could not find uuid '%s' in database" %
                        (uuid), file=sys.stderr)

        if _args.keyword is not None:
            for keyword in _args.keyword:
                print("keyword=%s" % keyword)
                if keyword in _dbkeywords_keyword:
                    print("processing keyword %s:" % keyword)
                    photos.extend(_dbkeywords_keyword[keyword])
                else:
                    print("Could not find keyword '%s' in database" %
                        (keyword), file=sys.stderr)

        if _args.person is not None:
            for person in _args.person:
                print("person=%s" % person)
                if person in _dbfaces_person:
                    print("processing person %s:" % person)
                    photos.extend(_dbfaces_person[person])
                else:
                    print("Could not find person '%s' in database" %
                        (person), file=sys.stderr)

    if _debug:
        pp = pprint.PrettyPrinter(indent=4)
        print("Photos to process:")
        pp.pprint(photos)

    # process each photo
    photopath = ""
    print("Found %d photos to process" % len(photos))
    for uuid in photos:
        vol = _dbphotos[uuid]['volume']
        if vol is not None:
            photopath = os.path.join('/Volumes', vol, _dbphotos[uuid]['imagePath'])
        else:
            photopath = os.path.join(masters_path, _dbphotos[uuid]['imagePath'])

        if _dbphotos[uuid]['isMissing'] == 1:
            print("Skipping photo not downloaded from cloud: %s" % (photopath))
            continue

        #todo: need more robust test interface--process_photo should show what it would do
        if not _args.test:
            print("processing photo: %s " % (photopath))
            process_photo(uuid, photopath)
        else:
            print("TEST: processing photo: %s " % (photopath))

    # start Photos again
    # scpt_launch.run()
#main

if __name__ == "__main__":
    main()
