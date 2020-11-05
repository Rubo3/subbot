import json
import os

class PathLikeEncoder(json.JSONEncoder):
    """Adds support for encoding os.PathLike objects in JSON.
    """

    def default(self, obj):
        if isinstance(obj, os.PathLike):
            return os.fspath(obj)
        return json.JSONEncoder.default(self, obj)

def read_json(path, mode="r", encoding='utf-8', object_pairs_hook=dict):
    with open(path, mode=mode, encoding=encoding) as json_file:
        return json.load(json_file, object_pairs_hook=object_pairs_hook)

def read_json_dict(path, mode="r", encoding='utf-8', object_pairs_hook=dict, return_=dict):
    try:
        return read_json(path, mode=mode, encoding=encoding, object_pairs_hook=object_pairs_hook)
    except:
        # logging function
        return return_()

def write_json(obj, path, ensure_ascii=True, indent=2):
    with open(path, 'w') as json_file:
        json.dump(obj, json_file, ensure_ascii=ensure_ascii, cls=PathLikeEncoder, indent=indent)
