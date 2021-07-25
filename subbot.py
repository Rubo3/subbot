from multiprocessing import cpu_count, Lock, Process
from os.path import isfile
from pathlib import Path
from signal import SIGINT, signal
import sys
from subprocess import CalledProcessError, run
from traceback import print_exc

from pymkv import identify_file, ISO639_2_languages, MKVFile, MKVTrack, verify_matroska, \
    verify_mkvmerge

# TODO:
# - Add the --mkvmerge_path argument, generate_mux_queue will have to be split in two functions
#   one will create the paths dictionary and track the optional arguments, the other will generate
#   the mux queue.
# - To make it composable, maybe add an argument to let it print the muxed filenames only (and only
#   them? only if piped? and another column with the project name? one per line?) and make use of the
#   standard error interface to pass the errors.
# - Rewrite get_properties in order to support the other separators:
#   (https://gitlab.com/mbunkus/mkvtoolnix/-/wikis/Detecting-track-language-from-filename).
# - Rewrite generate_mux_queue logic to be independent of videos and subtitles, check only filenames.

def sigint_handler():
    signal(SIGINT, lambda signalnum, stack_frame: sys.exit(0))

def generate_mux_queue(args):
    arg_index = 0
    args_len = len(args)
    mux_queue = []
    paths = {}
    subtitles = set()
    videos = set()

    while arg_index < args_len:
        arg = args[arg_index]
        if isfile(arg):
            info = identify_file(arg)
            if info['container']['recognized'] is True and info['container']['supported'] is True:
                file_type = info['container']['type']
                if file_type == 'SSA/ASS subtitles':
                    subtitles.add(Path(arg))
                elif file_type == 'Matroska' or file_type == 'QuickTime/MP4':
                    videos.add(Path(arg))
            else:
                print(f'Could not recognise "{arg}", skipping...')
        elif arg == '--output' or arg == '-o' and arg_index + 1 < args_len:
            output_path = args[arg_index + 1]
            paths[output_path] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}
            subtitles.clear()
            videos.clear()
            arg_index += 1
        arg_index += 1
    if args_len >= 2 and (args[-2] != '--output' or args[-2] != '-o'):
        paths[''] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}

    for output_path in paths:
        subtitles = paths[output_path]['subtitles']
        videos = paths[output_path]['videos']

        for video in videos:
            job = {
                'video_path': video,
                'output_path': Path(output_path) if output_path else video.parent.absolute(),
                'subtitles': {}
            }
            discard_subtitles = []

            for subtitle in subtitles:
                if strip_filename(subtitle.stem) == video.stem:
                    discard_subtitles.append(subtitle)
                    properties = get_properties(subtitle.stem)
                    if not properties:
                        print(f'No property has been found in {subtitle}, skipping...')
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

    splitted_filename = filename.split(sep=' [') # there could be more than one ' [' in the name,
    properties_string = splitted_filename[-1] # we need the last one, that's where the properties are
    if not properties_string[-1] == ']': # last character must be one of the special characters supported
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

def mux_mkv(mkv_path, subtitle_properties, mux_path, mkvmerge_path):
    mkv = MKVFile(mkv_path, mkvmerge_path=mkvmerge_path)
    # Convert the list of custom dictionaries returned by get_track()
    # into a list of standard dictionaries.
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
        else:
            for track in current_tracks:
                if track['_track_type'] == 'subtitles' \
                and track['track_name'] == subtitle_track.track_name:
                    mkv.replace_track(track['_track_id'], subtitle_track)
                    break
            else:
                mkv.add_track(subtitle_track)

    mkvmerge_command = mkv.command(mux_path, subprocess=True)
    run(mkvmerge_command, check=True, capture_output=True, text=True)

def worker(jobs, lock, mkvmerge_path):
    for job in jobs:
        subtitles = job['subtitles']
        output_path = job['output_path']
        video_path = job['video_path']
        video_name = video_path.name
        mux_path = get_available_path(output_path / (video_path.stem + '.mkv'))

        with lock:
            print(f'Muxing {video_name} in {mux_path}... ')
        try:
            mux_mkv(video_path, subtitles, mux_path, mkvmerge_path)
        except CalledProcessError as cpe:
            with lock:
                print('----------')
                print('mkvmerge gave the following messages:')
                for line in cpe.stdout.splitlines():
                    if line.startswith('Warning') or line.startswith('Error'):
                        print(line)
                print('----------')
                if cpe.returncode == 2:
                    print(f'Could not mux {video_name} in {mux_path}')
                    continue
        except Exception:
            with lock:
                print('----------')
                print(f'An exception occurred while muxing {video_name} in {mux_path}, skipping...')
                print_exc()
                print('----------')
            continue

        with lock:
            print(f'Done muxing {video_name} in {mux_path}')

def main(args, mkvmerge_path=None):
    if not mkvmerge_path:
        mkvmerge_path = 'mkvmerge'

    if not verify_mkvmerge(mkvmerge_path):
        print("Could not find mkvmerge, please add it to $PATH")
        return

    mux_queue = generate_mux_queue(args)
    total_jobs = len(mux_queue)
    if total_jobs == 0:
        return

    available_cores = cpu_count()
    num_workers = available_cores if available_cores <= total_jobs else total_jobs
    worker_jobs, remaining_jobs = divmod(total_jobs, num_workers)
    lock = Lock()
    processes = []

    for _ in range(num_workers):
        worker_queue = []
        if len(mux_queue) >= worker_jobs:
            additional_load = 0
            if remaining_jobs:
                additional_load = 1
                remaining_jobs -= 1
            num_jobs = worker_jobs + additional_load
            worker_queue = mux_queue[:num_jobs]
            mux_queue = mux_queue[num_jobs:]
        else:
            worker_queue = mux_queue
            mux_queue = []
        process = Process(target=worker, args=(worker_queue, lock, mkvmerge_path))
        processes.append(process)
        process.start()

    [process.join() for process in processes]

if __name__ == '__main__':
    sigint_handler()
    if len(sys.argv) > 1:
        main(sys.argv[1:])
    else:
        print('Upcoming help message...')
