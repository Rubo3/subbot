# sheldon woodward
# 3/24/18

"""Verification functions for mkvmerge and associated files."""

import json
import os
from os.path import expanduser, isfile
from pathlib import Path
from re import match
from shutil import which
import subprocess as sp


def verify_mkvmerge(mkvmerge_path='mkvmerge'):
    """Verify mkvmerge is working.

    mkvmerge_path (str):
        Alternate path to mkvmerge if it is not already in the $PATH variable.
    """
    return which(mkvmerge_path) is not None

def identify_file(file_path, mkvmerge_path='mkvmerge'):
    """Get information about about the source file. Same as `mvkmerge -J <file_path>`."""
    if not isinstance(file_path, (str, os.PathLike)):
        raise TypeError(f'"{file_path}" is not of type str or os.PathLike')
    if not isfile(file_path):
        raise FileNotFoundError(f'"{file_path}" does not exist')
    try:
        info = json.loads(sp.check_output([mkvmerge_path, '-J', file_path]).decode())
    except sp.CalledProcessError:
        raise ValueError(f'"{file_path}" could not be opened')
    return info

def verify_matroska(file_path, mkvmerge_path='mkvmerge'):
    """Verify if a file is a Matroska file.

    file_path (str):
        Path of the file to be verified.
    mkvmerge_path (str):
        Alternate path to mkvmerge if it is not already in the $PATH variable.
    """
    info = identify_file(file_path, mkvmerge_path)
    return info['container']['type'] == 'Matroska'


def verify_recognized(file_path, mkvmerge_path='mkvmerge'):
    """Verify a file is recognized by mkvmerge.

    file_path (str):
        Path to the file to be verified.
    mkvmerge_path (str):
        Alternate path to mkvmerge if it is not already in the $PATH variable.
    """
    info = identify_file(file_path, mkvmerge_path)
    return info['container']['recognized']


def verify_supported(file_path, mkvmerge_path='mkvmerge'):
    """Verify a file is supported by mkvmerge.

    file_path (str):
        Path to the file to be verified.
    mkvmerge_path (str):
        Alternate path to mkvmerge if it is not already in the $PATH variable.
    """
    info = info = identify_file(file_path, mkvmerge_path)
    return info['container']['supported']
