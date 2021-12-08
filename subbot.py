from os.path import isfile, isdir
from pathlib import Path
from signal import SIGINT, signal
from subprocess import CalledProcessError, run
import sys
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
    signal(SIGINT, lambda signalnum, stack_frame: sys.exit(0))

def generate_mux_queue(args):
    paths = {}
    subtitles = set()
    videos = set()

    for i, arg in enumerate(args):
        if isfile(arg):
            container = identify_file(arg)['container']
            if container['recognized'] is False or container['supported'] is False:
                print(f'Unrecognised container for "{arg}", skipping...')
                continue
            file_type = container['type']
            if file_type == 'SSA/ASS subtitles':
                subtitles.add(Path(arg))
            elif file_type in {'Matroska', 'QuickTime/MP4'}:
                videos.add(Path(arg))
        elif arg in {'--output', '-o'} and i + 1 < len(args) and isdir(args[i + 1]):
            if len(subtitles) != 0 and len(videos) != 0:
                output_path = args[i + 1]
                paths[Path(output_path)] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}
            subtitles.clear()
            videos.clear()

    if len(subtitles) != 0 and len(videos) != 0:
        paths[Path.cwd()] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}

    mux_queue = []
    for output_path in paths:
        subtitles = paths[output_path]['subtitles']
        videos = paths[output_path]['videos']

        for video in videos:
            job = {
                'output_path': output_path,
                'subtitles': {},
                'video_path': video
            }
            discard_subtitles = []

            for subtitle in subtitles:
                if strip_filename(subtitle.stem) == video.stem:
                    discard_subtitles.append(subtitle)
                    properties = get_properties(subtitle.stem)
                    if not properties:
                        print(
                            f'No property found in "{subtitle}", skipping...',
                            file=sys.stderr
                        )
                        continue
                    job['subtitles'][subtitle] = properties
            [subtitles.discard(sub) for sub in discard_subtitles]
            if len(job['subtitles']) > 0:
                mux_queue.append(job)
    return mux_queue

def strip_filename(filename):
    splitted = filename.split(sep=' [')
    if len(splitted) == 1:
        return filename
    # The last string contains the subtitle track properties, if any, or, if naught, the MKV name.
    return ' ['.join(splitted[:-1])

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

def get_available_path(path):
    copy_counter = 0
    path_stem = path.stem
    # Check if the path already contains a copy counter.
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
    output_path, subtitles, video_path = job
    mux_path = get_available_path(output_path / (video_path.stem + '.mkv'))

    try:
        mux(video_path, subtitles, mux_path, mkvmerge_path)
        print(f'"{video_path}" -> "{mux_path}"')
    except CalledProcessError as cpe:
        print(
            f'While muxing {video_path} in {mux_path}, `mkvmerge` gave the following messages:',
            file=sys.stderr
        )
        for line in cpe.stdout.splitlines():
            if line.startswith('Warning') or line.startswith('Error'):
                print(line, file=sys.stderr)
        if cpe.returncode == 2:
            print(f'Could not mux {video_path} in {mux_path}\n', file=sys.stderr)
    except Exception:
        print(
            f'While muxing {video_path} in {mux_path}, an exception occurred, skipping...',
            file=sys.stderr
        )
        print_exc(file=sys.stderr)

def main(args, mkvmerge_path = 'mkvmerge'):
    if len(args) < 2:
        print('Usage: python subbot.py file1 file2 ... fileN [--output dir]')
        return

    if not verify_mkvmerge(mkvmerge_path):
        print('Could not find `mkvmerge`, please add it to $PATH')
        return

    mux_queue = generate_mux_queue(args)
    for job in mux_queue:
        process(job, mkvmerge_path)

if __name__ == '__main__':
    sigint_handler()
    main(sys.argv[1:])
