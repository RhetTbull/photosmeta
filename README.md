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
   https://github.com/orangeturtle739/photos-export
   https://github.com/guinslym/pyexifinfo/tree/master/pyexifinfo


### Warning ###
NOTE: This is my very first python project. Using this script might
completely destroy your Photos library.  You have been warned! :-)

### License ###

See LICENSE.md

## Things To-Do ###
todo: progress bar for photos to process
todo: do ratings? XMP:Ratings, XMP:RatingsPercent
todo: position data (lat / lon)
todo: option to export then apply tags (e.g. don't tag original)
todo: cleanup single/double quotes
todo: standardize/cleanup exception handling in helper functions
todo: how are live photos handled
todo: use -stay_open with exiftool to aviod repeated subprocess calls
todo: right now, options (keyword, person, etc) are OR...add option for AND
        e.g. only process photos in album=Test AND person=Joe
todo: options to add:
--save_backup (save original file)
--export (export file instead of edit in place)
todo: test cases: 
    1) photo edited in Photos
    2) photo edited in external editor 
    3) photo where original in cloud but not on device (RKMaster.isMissing)
