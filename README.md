# Summary

This script will extract known metadata from Apple's Photos library and
write this metadata to EXIF/IPTC/XMP fields in the photo file
For example: Photos knows about Faces (personInImage) but does not
preserve this data when exporting the original photo

Metadata currently extracted and where it is placed:
Photos Faces --> XMP:PersonInImage, XMP:Subject

Photos keywords --> XMP:TagsList, IPTC:Keywords

Photos title --> XMP:Title

Photos description --> IPTC:Caption-Abstract, EXIF:ImageDescription, XMP:Description

title and description are overwritten in the destination file
faces and keywords are merged with any data found in destination file (removing duplicates)

Optionally, will write keywords and/or faces (persons) to
  Mac OS native keywords (xattr kMDItemUserTags)

## Installation

I recommend using [pipx](https://github.com/pipxproject/pipx)

`pipx install --spec git+https://github.com/RhetTbull/photosmeta.git photosmeta`

or install using setup.py:

`python setup.py install`

## Usage

```
usage: photosmeta [-h] [--database DATABASE] [-v] [-f] [--test]
                   [--keyword KEYWORD] [--album ALBUM] [--person PERSON]
                   [--uuid UUID] [--all] [--inplace] [--showmissing]
                   [--noprogress] [--version] [--xattrtag] [--xattrperson]
                   [--list {keyword,album,person}] [--export EXPORT]

optional arguments:
  -h, --help            show this help message and exit
  --database DATABASE   database file [will default to database last opened by
                        Photos]
  -v, --verbose         print verbose output
  -f, --force           Do not prompt before processing
  --test                list files to be updated but do not actually udpate
                        meta data
  --keyword KEYWORD     only process files containing keyword
  --album ALBUM         only process files contained in album
  --person PERSON       only process files tagged with person
  --uuid UUID           only process file matching UUID
  --all                 process all photos in the database
  --inplace             modify all photos in place (don't create backups). If
                        you don't use this option, exiftool will create a
                        backup image with format filename.extension_original
                        in the same folder as the original image
  --showmissing         show photos which are in the database but missing from
                        disk. Will *not* process other photos--e.g. will not
                        modify metadata.For example, this can happen because
                        the photo has not been downloaded from iCloud.
  --noprogress          do not show progress bar; helpful with --verbose
  --version             show version number and exit
  --xattrtag            write tags/keywords to file's extended attributes
                        (kMDItemUserTags) so you can search in spotlight using
                        'tag:' May be combined with -xattrperson CAUTION: this
                        overwrites all existing kMDItemUserTags (to be fixed
                        in future release)
  --xattrperson         write person (faces) to file's extended attributes
                        (kMDItemUserTags) so you can search in spotlight using
                        'tag:' May be combined with --xattrtag CAUTION: this
                        overwrites all existing kMDItemUserTags (to be fixed
                        in future release)
  --list {keyword,album,person}
                        list keywords, albums, persons found in database then
                        exit: --list=keyword, --list=album, --list=person
  --export EXPORT       export photos before applying metadata; set EXPORT to
                        the export path will leave photos in the Photos
                        library unchanged and only add metadata to the
                        exported photos
```

## Examples

Update metadata for all photos in the Photos database.  Do not create backups of the image files (modify inplace):

```
photosmeta --all --inplace
```

 Export all photos with keywords "Kids" to the Desktop and update their metadata.  Also set the OS X file tag so keywords/tags can be searched/seen in the Finder:

 ```
 photosmeta --keyword Kids --xattrtag --export ~/Desktop
 ```

## Dependencies

  [exiftool](https://www.sno.phy.queensu.ca/~phil/exiftool/) by Phil Harvey:

This code was inspired by [photo-export](https://github.com/patrikhson/photo-export) Copyright (c) 2015 Patrik Fältström <paf@frobbit.se>

## See Also

   [osxphotos](https://github.com/RhetTbull/osxphotos) python module for manipulating Apple's Photos library

   [photos-export](https://github.com/orangeturtle739/photos-export) does something similar for older versions of the Photos database

   [pyexifinfo](https://github.com/guinslym/pyexifinfo) Python wrapper for [exiftool](https://www.sno.phy.queensu.ca/~phil/exiftool/)

## Warning

This script modifies files in your Photos library.  Though I've done extensive testing, it's quite possible this could lead to data corruption or loss.  I highly recomend you have a complete backup of your Photos library before using this script.

Tested with MacOS 10.13.6 / Photos Version 3.0 (3291.13.210) and with MacOS 10.14.6 / Photos Version 4.0 (3461.7.140).  To use this with MacOS 10.15 / Photos 5, be sure you have the latest version of osxphotos: 

`python -m pip install --upgrade osxphotos`

## License

MIT License, see LICENSE.md
