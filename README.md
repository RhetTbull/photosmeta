# Summary

**NOTE: This project is no longer maintained.  Please take a look at [osxphotos](https://github.com/RhetTbull/osxphotos) which is maintained and includes much more functionality for working with Mac Photos than this project did.**

This script will extract known metadata from Apple's Photos library and write this metadata to EXIF/IPTC/XMP fields in the photo file. For example: Photos knows about Faces (personInImage) but does not preserve this data when exporting the original photo. Using photosmeta, you can export photos while preserving the metadata such as Faces, keywords, etc.  This script can also be run to modify your Photos library in place and add metadata to Mac extended attributes so that you can find photos in your Photos database using Spotlight.  For example, after installing, run:

`python3 -m photosmeta --inplace --all --xattrtag` 

or 

`photosmeta --inplace --all --xattrtag`

then in the Spotlight bar, searching for "tag:kids" will find all photos in Photos with keyword="kids" and open those files directly in Photos. 

Metadata currently extracted and where it is placed:

Photos Faces --> XMP:PersonInImage (and optionally XMP:TagsList, IPTC:Keywords, XMP:Subject)

Photos keywords --> XMP:TagsList, IPTC:Keywords, XMP:Subject

Photos title --> XMP:Title

Photos description --> IPTC:Caption-Abstract, EXIF:ImageDescription, XMP:Description

Photos albums --> optionally XMP:TagsList, IPTC:Keywords, XMP:Subject 

title and description are overwritten in the destination file
faces and keywords are merged with any data found in destination file (removing duplicates)

Optionally, will write keywords and/or faces (persons) to
  Mac OS native keywords/tags (xattr kMDItemUserTags)
  
If you only want to export photos, I strongly recommend you use the companion project [osxphotos](https://github.com/RhetTbull/osxphotos) which provides more control over the export process.  

## Installation

Requires Python 3.8

I recommend using [pipx](https://github.com/pipxproject/pipx)

`pipx install git+https://github.com/RhetTbull/photosmeta.git`

or install using setup.py:

`python3 setup.py install`

## Usage

```
usage: photosmeta [-h] [--database DATABASE] [--verbose] [-f] [--test]
                  [--keyword KEYWORD] [--album ALBUM] [--person PERSON]
                  [--uuid UUID] [--all] [--inplace] [--showmissing]
                  [--noprogress] [-v] [--xattrtag] [--xattrperson]
                  [--list {keyword,album,person}] [--export EXPORT]
                  [--export-by-date] [--edited] [--original-name]

optional arguments:
  -h, --help            show this help message and exit
  --database DATABASE   database file [will default to database last opened by
                        Photos]
  --verbose             print verbose output
  -f, --force           Do not prompt before processing
  --test                list files to be updated but do not actually udpate
                        meta data; most useful with --verbose
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
  -v, --version         show version number and exit
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
                        the export path; will leave photos in the Photos
                        library unchanged and only add metadata to the
                        exported photos
  --export-by-date      Automatically create output folders to organize photos
                        by date created (e.g. DEST/2019/12/20/photoname.jpg).
  --edited              Also update or export edited version of photo if one
                        exists; if exported, edited version will be named
                        photoname_edited.ext where photoname is name of
                        original photo and ext is extension of original photo.
                        Warning: recommend --edited not be used with --inplace
                        as it can cause errors when opening the photo in
                        Photos.app
  --original-name       Use photo's original filename instead of current
                        filename for export
  --albums-as-keywords  Store album names as keywords
  --persons-as-keywords Store person names as keywords
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

Export all photos to ~/Desktop/export and update their metadata.  Add person name as a spotlight tag.  Also export edited versions of the photos. Use original name instead of current name for exported photos. Organize exported photos in folders by creation date (e.g. ~/Desktop/export/2019/12/20/photo.jpg)

```
photosmeta --all --xattrtag --xattrperson --edited --original-name --export-by-date --export ~/Desktop/export
```

## Dependencies

  [exiftool](https://exiftool.org/) by Phil Harvey:

This code was inspired by [photo-export](https://github.com/patrikhson/photo-export) Copyright (c) 2015 Patrik Fältström <paf@frobbit.se>

## See Also

   [osxphotos](https://github.com/RhetTbull/osxphotos) python module for manipulating Apple's Photos library.  Used by photosmeta to read the Photos database.

   [photos-export](https://github.com/orangeturtle739/photos-export) does something similar for older versions of the Photos database.

   [pyexifinfo](https://github.com/guinslym/pyexifinfo) Python wrapper for [exiftool](https://exiftool.org/)

## Warning

This script may modify files in your Photos library.  Though I've done extensive testing, it's quite possible this could lead to data corruption or loss.  I highly recomend you have a complete backup of your Photos library before using this script, especially if using --inplace and not using --export.  See [license](LICENSE.md): this software is "provided \"as-is\", without warranty of any kind..."

Tested with MacOS 10.13.6 / Photos Version 3.0 (3291.13.210), MacOS 10.14.6 / Photos Version 4.0 (3461.7.140), and MacOS 10.15.1 / Photos 5.0 (111.16.180). 

## License

[MIT License](LICENSE.md)
