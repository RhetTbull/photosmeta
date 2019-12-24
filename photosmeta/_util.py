# util functions for photosmeta

import os.path
import pathlib
import subprocess

import osxmetadata


def check_file_exists(filename):
    """ return true if a file exists on disk and is not a directory, """
    """ otherwise return false """

    filename = os.path.abspath(filename)
    return os.path.exists(filename) and not os.path.isdir(filename)


def build_list(lst):
    """ input: array of elements that may be a string or list """
    """ returns: appends all input items to a list and returns the list """
    tmplst = []
    for x in lst:
        if x is not None:
            if isinstance(x, list):
                tmplst = tmplst + x
            else:
                tmplst.append(x)
    return tmplst


# TODO: remove this, I don't think it's needed now
def copyfile_with_osx_metadata(src, dest, overwrite_dest=False, findercomments=False):
    """ copy file from src (source) to dest (destination) """
    """ src is path with filename, dest is path only """
    """ if overwrite_dest = False (default), will create dest file in form 'filename (1).ext', """
    """     'filename (2).ext', and so on if dest file already exists"""
    """ if overwrite_dest = True, will overwrite existing dest file of same name as src """
    """ raises eception if src is not a file and if path is not a directory """
    """ dest file will have same name as src file but if file already exists """
    """ will be named file (1).ext, file (2).ext, etc """
    """ copy is done with subprocess call to system "ditto" because other copy methods don't preserve metadata """
    """ ditto does preserve Finder comments so those are copied with osxmetadata if findercomments=True """
    """ only works on mac OSX """
    """ returns pathlib.Path(dest) object """

    src = pathlib.Path(src)
    dest = pathlib.Path(dest)

    src = src.expanduser().resolve()
    dest = dest.expanduser().resolve()

    # check that source file exists
    if not src.is_file():
        raise ValueError(f"file {src} does not appear to exist or is not a file")

    # check that destination is a directory
    if not dest.is_dir():
        raise ValueError(
            f"destination {dest} does not appear to exist or is not a directory"
        )

    dest = dest / src.name

    # check to see if file exists and if so, add (1), (2), etc until we find one that works
    if not overwrite_dest:
        count = 1
        dest_new = dest
        while dest_new.exists():
            dest_new = dest.parent / f"{dest.stem} ({count}){dest.suffix}"
            count += 1
        dest = dest_new

    # if error on copy, subprocess will raise CalledProcessError
    subprocess.run(["/usr/bin/ditto", src, dest], check=True, stderr=subprocess.PIPE)

    if findercomments:
        md_src = osxmetadata.OSXMetaData(src)
        md_dest = osxmetadata.OSXMetaData(dest)
        md_dest.finder_comment = md_src.finder_comment

    return dest
