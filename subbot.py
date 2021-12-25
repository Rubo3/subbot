from os.path    import isfile, isdir
from pathlib    import Path
import re
from shutil     import which
from signal     import SIGINT, signal
import subprocess
from sys        import argv, stderr, stdout, exit as sysexit
from traceback  import print_exc

from pymkv import identify_file, ISO639_2_languages, MKVFile, MKVTrack, verify_matroska, \
    verify_mkvmerge

# TODO:
# - Add the `--mkvmerge` and `-m` arguments.
# - Rewrite `get_properties` in order to support the other separators
#   (https://gitlab.com/mbunkus/mkvtoolnix/-/wikis/Detecting-track-language-from-filename).
# - Rewrite `generate_mux_queue logic` to be independent of videos and subtitles,
#   check only filenames.
# - Rewrite the logic of `mux` to make use of swap_tracks, move_track, etc.

MKVMERGE_PATH = which('mkvmerge') or 'mkvmerge'

# Shut down gracefully.
def sigint_handler():
    stdout.flush()
    signal(SIGINT, lambda signalnum, stack_frame: sysexit(0))

def identify_files(args):
    paths = {}
    subtitles = set()
    videos = set()

    for i, arg in enumerate(args):
        if isfile(arg):
            container = identify_file(arg)['container']
            if not container['recognized']:
                print(f"Unrecognised container of '{arg}', skipping...", file=stderr)
                continue
            if not container['supported']:
                print(f"Unsupported container of '{arg}', skipping...", file=stderr)
                continue
            file_type = container['type']
            if file_type == 'SSA/ASS subtitles':
                subtitles.add(Path(arg))
            elif file_type in {'Matroska', 'QuickTime/MP4'}:
                videos.add(Path(arg))
        elif arg in {'--output', '-o'} and i + 1 < len(args) and isdir(args[i + 1]):
            if subtitles and videos:
                output_path = args[i + 1]
                paths[Path(output_path)] = {'subtitles': subtitles, 'videos': videos}
            subtitles = set()
            videos = set()
        elif Path(arg) not in paths:
            print(f"Unrecognised '{arg}', skipping...", file=stderr)
    if subtitles and videos:
        paths[Path.cwd()] = {'subtitles': subtitles, 'videos': videos}
    return paths

def generate_mux_queue(paths):
    mux_queue = []
    for output_path in paths:
        subtitles = paths[output_path]['subtitles']
        videos = paths[output_path]['videos']

        for video in videos:
            check_match = lambda sub: strip_properties(sub.stem) == video.stem
            association = {
                'video_path': video,
                'output_path': output_path,
                'mux_path': Path(),
                'subtitles': {},
            }

            matched_subs = set(filter(check_match, subtitles))
            subtitles -= matched_subs # subs in matched_subs won't be consumed by other videos
            for subtitle in matched_subs:
                properties = get_properties(subtitle.stem)
                if not properties:
                    print(f"No properties found in '{subtitle}', skipping...", file=stderr)
                    continue
                association['subtitles'][subtitle] = properties
            if not association['subtitles']:
                print(f"No subtitles associated to '{video}', skipping...", file=stderr)
                continue
            mux_queue.append(association)
    return mux_queue

def get_properties(filename):
    properties = {
        'track_name': None,
        '_track_id': 0,
        'language': 'und',
        'default_track': False,
        'forced_track': False,
    }
    # There could be more than one ' [' in the name, we need the last one, that's where the
    # properties are. The last character must be one of the special characters supported.
    splitted_filename = filename.split(sep=' [')
    properties_string = splitted_filename[-1]
    if not properties_string[-1] == ']':
        return {}

    properties_string = properties_string[:-1] # remove last ']'
    properties_list = properties_string.split(sep='][')
    for prop in properties_list:
        if prop.isdecimal():
            properties['_track_id'] = int(prop)
        elif prop[0] == prop[-1] == "'":
            properties['track_name'] = prop[1:-1]
        elif prop in ISO639_2_languages:
            properties['language'] = prop
        elif prop == 'default':
            properties['default_track'] = True
        elif prop == 'forced':
            properties['forced_track'] = True
    return properties

def strip_properties(filename):
    # There could be other ' [' before the properties, we shall consider them
    # part of the file name, thus `splitted` is a list of strings, not just a string.
    splitted = filename.split(sep=' [')
    if len(splitted) == 1: # `filename` does not contain properties
        return filename
    # The properties are in the last string, so we don't consider them here.
    return ' ['.join(splitted[:-1])

def first_available_path(path):
    copy_counter = 0
    path_stem = path.stem
    # Check if the path already contains a copy counter N of type ' (N)'.
    if path_stem[-1] == ')':
        splitted_stem = path_stem.split(' (')
        counter_candidate = splitted_stem[-1]
        if counter_candidate.isdecimal():
            copy_counter += counter_candidate
            path_stem = ')'.join(splitted_stem) # remove trailing ')'
    while path.exists():
        copy_counter += 1
        path = path.parent / (path_stem + f' ({copy_counter})' + path.suffix)
    return path

def mux(association):
    video_path = association['video_path']
    mux_path = association['mux_path']
    subtitles_properties = association['subtitles']

    try:
        mkv = MKVFile(video_path, mkvmerge_path=MKVMERGE_PATH)
        # Convert the list of MKVTracks (custom, not iterable dictionaries)
        # into a list of standard, iterable dictionaries.
        current_tracks = eval(str(mkv.get_track()))

        for subtitle_path in subtitles_properties:
            track_id = subtitles_properties[subtitle_path].pop('_track_id', 0)
            subtitle_track = MKVTrack(
                file_path=subtitle_path,
                mkvmerge_path=MKVMERGE_PATH,
                **subtitles_properties[subtitle_path]
            )
            if 0 <= track_id < len(current_tracks) \
            and current_tracks[track_id]['_track_type'] == 'subtitles':
                mkv.replace_track(track_id, subtitle_track)
                continue
            for track in current_tracks:
                if track['_track_type'] == 'subtitles' \
                and track['track_name'] == subtitle_track.track_name:
                    mkv.replace_track(track['_track_id'], subtitle_track)
                    break
            else:
                mkv.add_track(subtitle_track)

        mkvmerge_command = mkv.command(mux_path, subprocess=True)
        # Add option to parse non-translated, `\n`-terminated (instead of `\r`) lines.
        mkvmerge_command.insert(1, '--gui-mode')
        process = subprocess.Popen(mkvmerge_command, stdout=subprocess.PIPE, text=True, bufsize=1)
        return process
    except Exception:
        print(
            f"While muxing '{video_path}' in '{mux_path}', an exception occurred, skipping...",
            file=stderr
        )
        print_exc(file=stderr)
        return None

# To be set by other users of `main`.
def show_progress(process, mux_path):
    for line in process.stdout:
        if line.startswith(('#GUI#warning', '#GUI#error')):
            pbar.write(f'{line[5].upper()}{line[6:]}'.strip(), file=sys.stderr)

def merge(association):
    # The first available path
    output_path = association['output_path']
    video_path = association['video_path']
    mux_path = first_available_path(output_path / (video_path.stem + '.mkv'))
    association['mux_path'] = mux_path

    process = mux(association)
    if process is None:
        return
    show_progress(process, str(mux_path))
    returncode = process.wait()
    if returncode == 0:
        print(mux_path)
    elif returncode == 2:
        print(f"Could not mux '{video_path}' in '{mux_path}', skipping...", file=stderr)

def main(args):
    if len(args) < 2:
        print('Usage: subbot file1.vid file1.sub ... [--output dir]')
        return 0

    if not verify_mkvmerge(MKVMERGE_PATH):
        print('Could not find `mkvmerge`, please add it to $PATH.')
        return 1

    paths = identify_files(args)
    mux_queue = generate_mux_queue(paths)
    for association in mux_queue:
        merge(association)

if __name__ == '__main__':
    sigint_handler()
    args = argv[1:]
    sysexit(main(args))
