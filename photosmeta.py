#!/Users/rhet/anaconda3/bin/python

'''
todo: when writing meta data, zero the info first then add keywords also option to merge
todo: do ratings? XMP:Ratings, XMP:RatingsPercent
todo: include XMP:TagsList
todo: position data (lat / lon)
todo: uuid 
todo: option to export then apply tags (e.g. don't tag original)
todo: cleanup single/double quotes
todo: cleanup temp file

todo: how are live photos handled
todo: store person in XMP:Subject (that's what iPhoto does 
    (it also stores keywords there)) on export with IPTC to XMP

todo: add option to list keywords, persons, etc found in database --list

todo: right now, options (keyword, person, etc) are OR...add option for AND
        e.g. only process photos in album=Test AND person=Joe
todo: options to add:
--save_backup (save original file)
--keep_original_metadata
--export (export file instead of edit in place)

todo: test cases: 
    1) photo edited in Photos 
    2) photo edited in external editor 
    3) photo where original in cloud but not on device

See also:
    https://github.com/orangeturtle739/photos-export

'''

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
from warnings import warn
import objc
from Foundation import *
import CoreFoundation
import urllib.parse
import applescript
from plistlib import load 
from shutil import copyfile
import tempfile

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

def process_arguments():
    global _args
    global _verbose
    global _dbfile
    global _debug

    # Setup command line arguments
    parser = argparse.ArgumentParser()
    # one required argument: path to database file
    #parser.add_argument("DATABASE_FILE", help="path to Photos database file")
    parser.add_argument("--database",
                        help="database file [will default to Photos default file")
    parser.add_argument("-v", "--verbose", action="store_true", default=False,
                        help="print verbose output",)
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
                        help="modify all photos in place (don't export)")
    parser.add_argument("--list", action='append',
                        help="list keywords, albums, persons found in database" +
                        "--list=keyword, --list=album, --list=person")

    _args = parser.parse_args()
    _verbose = _args.verbose
    _dbfile = _args.database
    _debug = _args.debug

    if _args.keyword is not None:
        print("keywords: " + " ".join(_args.keyword))

def get_photos_library_path():
    #return the path to the Photos library
    plist_file = Path(str(Path.home()) + 
        "/Library/Containers/com.apple.Photos/Data/Library/Preferences/com.apple.Photos.plist")
    if plist_file.is_file():
        with open(plist_file, 'rb') as fp:
            pl = load(fp)
    else:
        warn('could not find plist file: ' + str(plist_file))
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
            warn("Could not extract photos URL String from IPXDefaultLibraryURLBookmark")
            return None

        return photospath
    else:
        warn("Could not get path to Photos database")
        return None
#get_photos_library_path

def copy_db_file(fname):
    #copies the sqlite database file to a temp file
    #returns the name of the temp file
    #required because python's sqlite3 implementation can't read a locked file
    fd, tmp = tempfile.mkstemp(suffix=".db",prefix="photos")
    do_log("copying " + fname +" to " + tmp)
    try:
        copyfile(fname,tmp)
    except:
        warn("copying " + fname +" to " + tmp)
        sys.exit()
    return tmp

# Handle progress bar (equivalent)
# TODO: this has some linting issues
# TODO: replace this code with https://pypi.org/project/progress/
_pbar_status_text = ""
_pbar_maxvalue = -1

def init_pbar_status(text, max):
    global _pbar_status_text
    global _pbar_maxvalue
    print("init: %s %s" % (text, max))
    _pbar_status_text = text
    _pbar_maxvalue = max


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
            sys.stdout.write('\r%s: %d' % (_pbar_status_text, theNum))
        sys.stdout.flush()


def close_pbar_status():
    global _pbar_status_text
    global _pbar_maxvalue
    if(not _verbose):
        sys.stdout.write('\r%s: [ %-30s ] %3d%%\n' %
                         (_pbar_status_text, format('#' * 30), 100))
    _pbar_maxvalue = -1
    _pbar_status_text = ""

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


def do_log(s):
    if(_verbose):
        print(s)


def open_sql_file(file):
    fname = file
    do_log("Trying to open database %s" % (fname))
    try:
        conn = sqlite3.connect("%s" % (fname))
        c = conn.cursor()
    except sqlite3.Error as e:
        print("An error occurred: %s %s" % (e.args[0], fname))
        sys.exit(3)
    do_log("SQLite database is open")
    return(conn, c)


def write_metadata_to_file(file, data):
    print("writeMetaDataToFile")
    do_log("writeMetaDataToFile: file = %s" % (file))
    pp = pprint.PrettyPrinter(indent=4)
    pp.pprint(data)
    return


def get_exiftool_path():
    global _exiftool
    result = subprocess.run(['which', 'exiftool'], stdout=subprocess.PIPE)
    exiftool_path = result.stdout.decode('utf-8')
    do_log("exiftool path = %s" % (exiftool_path))
    if exiftool_path is not "":
        return exiftool_path
    else:
        errstr = "Could not find exiftool"
        sys.exit(errstr)


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
    do_log("Have connection with database")

    # Look for all combinations of persons and pictures
    do_log("Getting information about persons")

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
        if not person[1] in _dbfaces_uuid:
            _dbfaces_uuid[person[1]] = []
        if not person[0] in _dbfaces_person:
            _dbfaces_person[person[0]] = []
        _dbfaces_uuid[person[1]].append(person[0])
        _dbfaces_person[person[0]].append(person[1])
        set_pbar_status(i)
        i = i + 1
    do_log("Finished walking through persons")
    close_pbar_status()

    do_log("Getting information about albums")
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
        do_log("%s %s" % (album[1], album[0]))
        set_pbar_status(i)
        i = i + 1
    do_log("Finished walking through albums")
    close_pbar_status()

    do_log("Getting information about keywords")
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
        do_log("%s %s" % (keyword[1], keyword[0]))
        set_pbar_status(i)
        i = i + 1
    do_log("Finished walking through keywords")
    close_pbar_status()

    do_log("Getting information about volumes")
    c.execute("select count(*) from RKVolume")
    init_pbar_status("Volumes", c.fetchone()[0])
    c.execute("select RKVolume.modelId, RKVolume.name from RKVolume")
    i = 0
    for vol in c:
        _dbvolumes[vol[0]] = vol[1]
        do_log("%s %s" % (vol[0], vol[1]))
        set_pbar_status(i)
        i = i + 1
    do_log("Finished walking through volumes")
    close_pbar_status()

    do_log("Getting information about photos")
    c.execute("select count(*) from RKVersion, RKMaster where RKVersion.isInTrash = 0 and " 
            + "RKVersion.type = 2 and RKVersion.masterUuid = RKMaster.uuid and "
            + "RKVersion.filename not like '%.pdf'")
    init_pbar_status("Photos", c.fetchone()[0])
    c.execute("select RKVersion.uuid, RKVersion.modelId, RKVersion.masterUuid, RKVersion.filename, "
            + "RKVersion.lastmodifieddate, RKVersion.imageDate, RKVersion.mainRating, "
            + "RKVersion.hasAdjustments, RKVersion.hasKeywords, RKVersion.imageTimeZoneOffsetSeconds, "
            + "RKMaster.volumeId, RKMaster.imagePath, RKVersion.extendedDescription, RKVersion.name "
            + "from RKVersion, RKMaster where RKVersion.isInTrash = 0 and RKVersion.type = 2 and "
            + "RKVersion.masterUuid = RKMaster.uuid and RKVersion.filename not like '%.pdf'")
    i = 0
    for row in c:
        set_pbar_status(i)
        i = i + 1
        uuid = row[0]
        do_log("i = %d, uuid = '%s, master = '%s" % (i, uuid, row[2]))
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
        do_log("Fetching data for photo %d %s %s %s %s %s: %s" %
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
        do_log("Removing temporary databse file" + tmp_db)
        os.remove(tmp_db)
    except:
        warn("Could not remove temporary database" + tmp_db)

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

def process_photo(uuid, photopath):
    #process a photo using exiftool
    global _args
    global _dbphotos
    return
   

def main():
    global _verbose
    global _dbfile
    global _args

    get_exiftool_path()
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
    do_log("filename = %s" % filename)

    #TODO: replace os.path with pathlib
    #TODO: clean this up -- we'll already know library_path
    library_path = os.path.dirname(filename)
    (library_path, tmp) = os.path.split(library_path)
    masters_path = os.path.join(library_path, "Masters")
    do_log("library = %s, masters = %s" % (library_path, masters_path))

    # if(not os.path.exists("%s/database/photos.db" % filename)):
    if (not os.path.exists(filename)):
        filename = None
        print("_dbfile %s does not exist" % filename)
        sys.exit(1)
    do_log("filename = %s" % filename)

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

        #build_exiftool_cmd()
        if not _args.test:
            print("processing photo: %s " % (photopath))
            process_photo(uuid, photopath)
        else:
            print("TEST: processing photo: %s " % (photopath))
            process_photo(uuid, photopath)


    # start Photos again
    # zzz scpt_launch.run()
if __name__ == "__main__":
    main()
