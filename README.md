### Summary ###
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

### Dependencies ###
  exiftool by Phil Harvey:
      https://www.sno.phy.queensu.ca/~phil/exiftool/

This code was inspired by photo-export by Patrick Fältström see:
  https://github.com/patrikhson/photo-export
  Copyright (c) 2015 Patrik Fältström <paf@frobbit.se>

### See Also ###

   [osxphotos](https://github.com/RhetTbull/osxphotos) python module for manipulating Apple's Photos library
	
   [photos-export](https://github.com/orangeturtle739/photos-export) does something similar for older versions of the Photos database

   [pyexifinfo](https://github.com/guinslym/pyexifinfo) Python wrapper for [exiftool](https://www.sno.phy.queensu.ca/~phil/exiftool/)


### Warning ###
This script modifies files in your Photos library.  Though I've done extensive testing, it's quite possible this could lead to data corruption or loss.  I highly recomend you have a complete backup of your Photos library before using this script.

### License ###

See LICENSE.md
