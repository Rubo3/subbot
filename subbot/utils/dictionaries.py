from collections import defaultdict
import os

### DefaultDict

def recursive_defaultdict():
    """Returns a recursive `defaultdict` dictionary.
    """

    # return defaultdict(recursive_defaultdict)
    return RecursiveDefaultDict()

def defaultdict_factory(d):
    """Custom JSON decoder which supports recursive `defaultdict` dictionaries.
    """

    new_dict = recursive_defaultdict()
    new_dict.update(d)
    return new_dict

class RecursiveDefaultDict(defaultdict):
    def __init__(self, default_factory = recursive_defaultdict, *args, **kwargs):
        super().__init__(default_factory, *args, **kwargs)

### PathDict

def recursive_pathdict():
        return PathDict(recursive_pathdict)

def pathdict_factory(d):
    """Custom JSON decoder which supports recursive `defaultdict` dictionaries.
    """

    new_dict = recursive_pathdict()
    new_dict.update(d)
    return new_dict

class PathDict(RecursiveDefaultDict):
    def __init__(self, default_factory = recursive_pathdict, *args, **kwargs):
        if args and args[0] == recursive_pathdict:
            if len(args) > 1:
                args = args[1:]
            else:
                args = ()
        super().__init__(default_factory, *args, **kwargs)

    def __getitem__(self, key):
        if isinstance(key, os.PathLike):
            key = os.fspath(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if isinstance(key, os.PathLike):
            key = os.fspath(key)
        if isinstance(value, os.PathLike):
            value = os.fspath(value)
        return super().__setitem__(key, value)
