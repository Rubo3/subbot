import os
from pathlib import Path

from PyInquirer.prompt import prompt
from pymkv import MKVFile, MKVTrack

from subbot.utils.dictionaries import PathDict
from subbot.utils.jsonutils import read_json_dict, write_json
from subbot.utils.misc import ask_directory

def get_mkv_name(string):
    """ We only know the string is probably in the form '... (...).extension',
    we don't know if there are other parenthesis, so we reverse it,
    remove the (now) first parenthesis, reverse it again and return it.
    """

    if string[-4:] == ".ass":
        string = string[:-4]

    if "(" in string and ")" in string[string.index("(") + 1:]:
        reversed_string = string[::-1]
        reversed_file_name = reversed_string[reversed_string.index("(") + 2:]
        file_name = reversed_file_name[::-1]

        reversed_properties = reversed_string[reversed_string.index(")") + 1:reversed_string.index("(")]
        properties = reversed_properties[::-1]
        return (file_name + ".mkv", properties)

    return (string + ".mkv", "")

def get_track_by_type(tracks, track_type, track_name = None, track_language = None, tags = None):
    """In the default MKV properties file, the '_tags' key inside a track dictionary
    is used as a unique identifier for that track, but when dealing with actual subtitle tracks,
    PyMKV treats this key in a different way, so this function can work with:

    - the 'tags' parameter only, if the tracks list passed in is not from an actual MKV file;
    - the 'track_name' and 'track_language' parameters only, otherwise.

    If none of these three parameters is passed in, it will return the first track which matches the 'track_type' parameter.

    Please remember to pass the right parameters depending on which type of tracks list you are working with.

    Why using 'track_name' and 'track_language', and not another property?
    This is an arbitrary choice used as a work around to retrieve the right track.
    We can not say a priori if the actual MKV tracks list  we are dealing with is the same of the default one
    (some properties may have been changed), but we can argue the track we want has the same name and the same language
    properties of the default one, so we can check whether this is true or not, and if it is true, we get our beloved track.

    The '_tags' property can't be used because PyMKV requires it to be a path, but within subbot it is treated as a unique identifier for a track.
    There could be better ways to retrieve the track we want without using the '_tags' property.
    If you have any suggestions please let me know.
    """

    for track in tracks:
        if track["_track_type"] == track_type:
            if not track_name and not track_language and not tags:
                return track
            elif track["track_name"] == track_name and track['_language'] == track_language and track.get("_tags", "") == tags:
                return track
            elif track["track_name"] == track_name and track['_language'] == track_language and not tags:
                return track
            elif track["track_name"] == track_name and not tags:
                return track
            elif track.get("_tags", "") == tags and not track_name and not track_language:
                return track
    return {}

def replace_subtitle(subtitle_path, mkv_path, default_track, output_path = "", tags = ""):
    if isinstance(subtitle_path, str):
        subtitle_path = Path(subtitle_path)
    if isinstance(mkv_path, str):
        mkv_path = Path(mkv_path)
    if isinstance(output_path, str):
        output_path = Path(output_path)
    elif not output_path:
        output_path = subtitle_path.parent

    default_track_name = default_track.get("track_name", "subtitles")
    default_track_id = default_track.get("_track_id", -1)
    default_language = default_track.get("_language", "und")

    mkv = MKVFile(str(mkv_path))
    # Convert the list of dictionaries returned by get_track() into an *actual* list of dictionaries.
    # It's quicker than converting the list into an *actual* list and every dictionary into *actual* dictionaries.
    current_tracks = eval(str(mkv.get_track()))
    current_subtitle_track = get_track_by_type(tracks = current_tracks,
                                               track_type = "subtitles",
                                               track_name = default_track_name,
                                               track_language = default_language)
    current_track_id = current_subtitle_track.get("_track_id", -1)

    subtitle_track = MKVTrack(file_path = subtitle_path,
                              track_name = default_track_name,
                              language = default_language,
                              default_track = default_track["default_track"],
                              forced_track = default_track["forced_track"])

    if current_track_id != -1 and default_track_id != -1:
        if current_track_id == default_track_id:
            mkv.replace_track(default_track_id, subtitle_track)
        elif current_track_id != default_track_id:
            mkv.remove_track(current_track_id)
            subtitle_track.track_id = default_track_id
            mkv.add_track(subtitle_track)
    else:   # current_track_id is None, so the file has no subtitle track
        mkv.add_track(subtitle_track)

    if output_path.is_dir():
        output_path = output_path / mkv_path.name
    # mkvmerge_command = mkv.command(output_path, subprocess=True)) # to inspect the command
    mkv.mux(output_path) # if the exit code is non-zero, it throws a CalledProcessError

def add_directory(project, project_path = None):
    question1 = {
        'type': 'confirm',
        'message': 'Do you want to manually edit the tracks before adding them to the MKV properties file? (you can always modify them later)',
        'name': 'tracks_manual_edit',
        'default': True,
    }
    question2 = {
        'type': 'confirm',
        'message': 'Have you finished modifying `tracks.json`?',
        'name': 'finished',
        'default': True,
    }
    question3 = {
        'type': 'confirm',
        'message': 'Do you want use these tracks for every other MKV inside this directory?',
        'name': 'global_tracks',
        'default': True,
    }
    properties_to_remove = [
        '_track_codec',
        'mkvmerge_path',
        '_file_path',
        '_tags',
        'no_chapters',
        'no_global_tags',
        'no_track_tags',
        'no_attachments'
    ]
    global_tracks = {}

    if not project_path:
        print(f"Select a directory which contains MKV files of your project:")
        project_path = ask_directory()

    mkv_files = [file_ for file_ in project_path.iterdir() if file_.is_file() and file_.suffix == ".mkv"]

    for mkv_file in mkv_files:
        if not global_tracks:
            mkv = MKVFile(project_path / mkv_file.name)
            tracks = eval(str(mkv.get_track()))

            print(f"Checking for subtitles in {mkv_file.name} and removing unnecessary tracks (audio, video) and properties... ")
            polished_tracks = []
            for track in tracks:
                if track.get("_track_type", "") == "subtitles":
                    for property_to_remove in properties_to_remove:
                        track.pop(property_to_remove, None)
                    polished_tracks.append(track)
            if polished_tracks:
                print("Subtitles found!")
            tracks = polished_tracks

            if prompt(question1)["tracks_manual_edit"]:
                cwd = Path.cwd()
                write_json(obj=tracks, path=cwd / "tracks.json")
                print(f"A `tracks.json` has been added to {cwd}.\n"
                       "Please modify it as you like it, save it and then press Enter.")
                while not prompt(question2):
                    print("Ok then, when you're done, press Enter.")
                tracks = read_json_dict(path=cwd / "tracks.json")
                Path.unlink(cwd / "tracks.json")

            if prompt(question3)["global_tracks"]:
                global_tracks = tracks

        project[project_path][mkv_file.name]["tracks"] = tracks

    return project

def add_project(mkv_properties):
    question1 = {
        "type": "input",
        "name": "project_name",
        "message": "Insert the project name",
        "default": "",
    }
    question2 = {
        'type': 'confirm',
        'message': 'Do you want to add a new directory?',
        'name': 'new_directory',
        'default': True,
    }
    global_project_name = False
    project_name = ""
    project_path = Path()

    while True:
        if not global_project_name:
            print(f"Select a directory which contains MKV files of your project:")
        else:
            print(f"Select a directory which contains MKV files of {project_name}:")
        project_path = ask_directory()

        if not global_project_name:
            question1["default"] = project_path.name
            project_name = prompt(question1)["project_name"]

        mkv_properties[project_name] = add_directory(mkv_properties[project_name], project_path)

        if prompt(question2)["new_directory"]:
            global_project_name = True
        else:
            break

    return mkv_properties

def create_mkv_properties(properties_path):
    question = {
        'type': 'confirm',
        'message': 'Do you want to add a new project?',
        'name': 'confirm',
        'default': True,
    }
    mkv_properties = PathDict()

    print("Create the list of MKV files you want to track.")
    while True:
        mkv_properties = add_project(mkv_properties)
        answer = prompt(question)["confirm"]
        if not answer:
            break

    write_json(obj=mkv_properties, path=properties_path / "mkv_properties.json")
    print(f"The MKV properties file has been saved in {properties_path}.")
    return mkv_properties

def check_differences(path1, path2):
    """Pretty bare function which checks if two MKVs have the exact same tracks,
    in which case it doesn't print anything. Otherwise it prints the keys
    whose value differ.
    If the two files have not the same number of tracks, the file whose tracks number
    is lesser is used as reference when comparing the tracks.
    """
    tracks = lambda mkv: eval(str(mkv.get_track()))

    tracks1 = tracks(MKVFile(path1))
    tracks2 = tracks(MKVFile(path2))

    length = len(tracks1) if len(tracks1) <= len(tracks2) else len(tracks2)

    for i in range(length):
        for key in tracks1[i].keys():
            if tracks1[i][key] != tracks2[i][key]:
                print(key)
