from os.path import isfile, isdir
from pathlib import Path
from signal import SIGINT, signal
from subprocess import CalledProcessError, run
from sys import argv, stderr, exit as _exit
from traceback import print_exc

from pymkv import identify_file, ISO639_2_languages, MKVFile, MKVTrack, verify_matroska, \
    verify_mkvmerge

# TODO:
# - Add the --mkvmerge_path argument, generate_mux_queue will have to be split in two functions
#   one will create the paths dictionary and track the optional arguments, the other will generate
#   the mux queue.
# - Rewrite get_properties in order to support the other separators
#   (https://gitlab.com/mbunkus/mkvtoolnix/-/wikis/Detecting-track-language-from-filename).
# - Rewrite generate_mux_queue logic to be independent of videos and subtitles, check only
#   filenames.
# - Check if it's better to get the mkvmerge binary path with an environment variable instead of
#   passing it down to each function.

# Shut down gracefully.
def sigint_handler():
    signal(SIGINT, lambda signalnum, stack_frame: _exit(0))

def generate_mux_queue(args):
    paths = {}
    subtitles = set()
    videos = set()

    for i, arg in enumerate(args):
        if isfile(arg):
            container = identify_file(arg)['container']
            if not container['recognized'] or not container['supported']:
                print(f'Unrecognised container for "{arg}", skipping...')
                continue
            file_type = container['type']
            if file_type == 'SSA/ASS subtitles':
                subtitles.add(Path(arg))
            elif file_type in {'Matroska', 'QuickTime/MP4'}:
                videos.add(Path(arg))
        elif arg in {'--output', '-o'} and i + 1 < len(args) and isdir(args[i + 1]):
            if subtitles and videos:
                output_path = args[i + 1]
                paths[Path(output_path)] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}
            subtitles.clear()
            videos.clear()

    if subtitles and videos:
        paths[Path.cwd()] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}

    mux_queue = []
    for output_path in paths:
        subtitles = paths[output_path]['subtitles']
        videos = paths[output_path]['videos']

        for video in videos:
            check_match = lambda sub: strip_properties(sub.stem) == video.stem
            job = {
                'output_path': output_path,
                'subtitles': {},
                'video_path': video
            }

            matched_subs = set(filter(check_match, subtitles))
            subtitles -= matched_subs # subs in matched_subs won't be consumed by other videos
            for subtitle in matched_subs:
                properties = get_properties(subtitle.stem)
                if not properties:
                    print(f'No properties found in "{subtitle}", skipping...', file=stderr)
                    continue
                job['subtitles'][subtitle] = properties
            if not job['subtitles']:
                print(f'No subtitles found for "{video}", skipping...', file=stderr)
                continue
            mux_queue.append(job)
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
        if prop.isdigit():
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

def get_available_path(path):
    copy_counter = 0
    path_stem = path.stem
    # Check if the path already contains a copy counter of the type ' (N)'.
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

def mux(mkv_path, subtitle_properties, mux_path, mkvmerge_path):
    mkv = MKVFile(mkv_path, mkvmerge_path=mkvmerge_path)
    # Convert the list of MKVTracks (custom, not iterable dictionaries) into a list of standard,
    # iterable dictionaries.
    current_tracks = eval(str(mkv.get_track()))

    for subtitle_path in subtitle_properties:
        track_id = subtitle_properties[subtitle_path].pop('_track_id', 0)
        subtitle_track = MKVTrack(
            file_path=subtitle_path,
            mkvmerge_path=mkvmerge_path,
            **subtitle_properties[subtitle_path]
        )
        # TODO: rewrite logic to make use of swap_tracks, move_track, etc.
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
    run(mkvmerge_command, check=True, capture_output=True, text=True)

def process(job, mkvmerge_path):
    output_path, subtitles, video_path = job.values()
    mux_path = get_available_path(output_path / (video_path.stem + '.mkv'))

    print(f'Muxing "{video_path}" in "{mux_path}"... ', end='')

    try:
        mux(video_path, subtitles, mux_path, mkvmerge_path)
    except CalledProcessError as cpe:
        print(
            f'While muxing {video_path} in {mux_path}, `mkvmerge` gave the following messages:',
            file=stderr
        )
        for line in cpe.stdout.splitlines():
            if line.startswith('Warning') or line.startswith('Error'):
                print(line, file=stderr)
        if cpe.returncode == 2:
            print(f'Could not mux {video_path} in {mux_path}', file=stderr)
    except Exception:
        print(
            f'While muxing {video_path} in {mux_path}, an exception occurred, skipping...',
            file=stderr
        )
        print_exc(file=stderr)

    print(f'done.')

def main(args, mkvmerge_path = 'mkvmerge'):
    if len(args) < 2:
        print('Usage: subbot file1.vid file1.sub ... [--output dir]')
        return

    if not verify_mkvmerge(mkvmerge_path):
        print('Could not find `mkvmerge`, please add it to $PATH')
        return

    mux_queue = generate_mux_queue(args)
    for job in mux_queue:
        process(job, mkvmerge_path)

if __name__ == '__main__':
    sigint_handler()
    main(argv[1:])
