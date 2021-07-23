from multiprocessing import cpu_count, Lock, Process
from pathlib import Path
from signal import SIGINT, signal
import sys
from subprocess import CalledProcessError, run
from traceback import print_exc

from pymkv import MKVFile, MKVTrack, verify_mkvmerge
from pymkv.ISO639_2 import iso639_2_languages

# TODO: check for duplicates, like `subbot KnK/0* Knk/1*`.
# to make it composable, let it only print the muxed filenames (and only them?; only if piped?*),
# and make use of the standard error interface to pass the errors.
# *maybe add an optional argument to only print the muxed filenames (and another column with the
# project name?) one per line.

def sigint_handler():
    signal(SIGINT, lambda signalnum, stack_frame: sys.exit(0))

# TODO: differentiate between general path arguments and configuration-specific path arguments.
def generate_mux_queue(args):
    arg_index = 0
    args_len = len(args)
    mux_queue = []
    paths = {}
    subtitles = set()
    videos = set()

    while arg_index < args_len:
        arg = args[arg_index]
        path_arg = Path(arg)
        if path_arg.is_file():
            if path_arg.suffix == '.ass':
                subtitles.add(arg)
            elif path_arg.suffix == '.mkv' or path_arg.suffix == '.mp4':
                videos.add(arg)
        elif arg == '--output' or arg == '-o' and arg_index + 1 < args_len:
            output_path = args[arg_index + 1]
            paths[output_path] = {'subtitles': subtitles.copy(), 'videos': videos.copy()}
            subtitles.clear()
            videos.clear()
            arg_index += 1
        arg_index += 1
    if args_len >= 2 and (args[-2] != '--output' or args[-2] != '-o'):
        paths[''] = {'subtitles': subtitles, 'videos': videos}

    for output_path in paths:
        subtitles = paths[output_path]['subtitles']
        videos = paths[output_path]['videos']

        while subtitles and videos:
            discard_subtitles = []
            video = Path(videos.pop())
            operation = {
                'mkv_path': video,
                'output_path': Path(output_path) if output_path else video.parent.absolute(),
                'subtitles': {}
            }

            for subtitle in subtitles:
                if get_stripped_filename(subtitle) == video.stem:
                    discard_subtitles.append(subtitle)
                    properties = get_properties(subtitle)
                    if not properties:
                        print(f'No property has been found in {subtitle}, skipping...')
                        continue
                    operation['subtitles'][subtitle] = properties
            [subtitles.discard(sub) for sub in discard_subtitles]
            if operation['subtitles']:
                mux_queue.append(operation)
    return mux_queue

# Special boundary characters to be supported:
# https://gitlab.com/mbunkus/mkvtoolnix/-/wikis/Detecting-track-language-from-filename
# TODO: must be rewritten in order to support the other separators
def get_stripped_filename(file_path):
    filename = Path(file_path).stem # works even with '.' as a separator
    splitted = filename.split(sep=' [')
    if len(splitted) == 1:
        return filename
    # The last string contains the subtitle track properties, if any, or, if naught, the MKV name.
    return ' ['.join(splitted[:-1])

def get_properties(file_path):
    default_properties = {
        'track_name': None,
        '_track_id': 0,
        'language': 'und',
        'default_track': False,
        'forced_track': False,
    }

    filename = Path(file_path).stem
    splitted = filename.split(sep=' [') # there could be more than one ' [' in the file name,
    properties = splitted[-1] # we need the last one, because that's where the properties are

    if not properties[-1] == ']': # last character must be one of the special characters supported
        return {}

    properties_list = []
    properties = properties[:-1] # removes last ']'
    properties_list = properties.split(sep='][')
    custom_properties = {}
    for prop in properties_list:
        if prop.isnumeric():
            custom_properties['_track_id'] = int(prop)
        elif prop[0] == prop[-1] == "'":
            custom_properties['track_name'] = prop[1:-1]
        elif prop in iso639_2_languages and not custom_properties.get('language', False):
            custom_properties['language'] = prop
        elif prop == 'default':
            custom_properties['default_track'] = True
        elif prop == 'forced':
            custom_properties['forced_track'] = True
    final_properties = default_properties.copy()
    final_properties.update(custom_properties)
    return final_properties

def first_available_path(path_pattern):
    if not Path.exists(path_pattern):
        return path_pattern

    copy_counter = 1
    path_parent = path_pattern.parent
    path_stem = path_pattern.stem
    # Check if the path already contains a copy counter.
    if path_stem[-1] == ')':
        splitted_stem = path_stem.split(' (')
        counter_candidate = splitted_stem[-1]
        if counter_candidate[:-1].isnumeric():
            copy_counter += counter_candidate[:-1]
            path_stem = ')'.join(splitted_stem) # remove trailing ')'

    while (path_parent / (path_stem + f' ({copy_counter})' + path_pattern.suffix)).exists():
        copy_counter += 1
    return path_parent / (path_stem + f' ({copy_counter})' + path_pattern.suffix)

def check_tracks(tracks):
    default_counter = 0
    for track in tracks:
        if track['_track_type'] == 'subtitles' and track['default_track'] is True:
            default_counter += 1
    if default_counter > 1:
        raise Exception('impossible to set more than one default subtitle track')

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

    check_tracks(tracks=eval(str(mkv.get_track())))
    mkvmerge_command = mkv.command(mux_path, subprocess=True)
    run(mkvmerge_command, check=True, capture_output=True, text=True)

def worker(operations, lock, mkvmerge_path):
    for operation in operations:
        subtitles = operation['subtitles']
        output_path = operation['output_path']
        mkv_path = Path(operation['mkv_path'])
        is_converted = False

        if mkv_path.suffix != '.mkv':
            mux_path = first_available_path(output_path / (mkv_path.stem + '.mkv.tmp'))
            mkvmerge_command = ['mkvmerge', '--output', f'{mux_path}', f'{mkv_path}']
            with lock:
                print(f'Converting {mkv_path.name} in {mux_path}... ')
            try:
                run(mkvmerge_command, check=True, capture_output=True, text=True)
            except CalledProcessError as cpe:
                with lock:
                    print('----------')
                    print('mkvmerge printed the following messages:')
                    for line in cpe.stdout.splitlines():
                        if line.startswith('Warning') or line.startswith('Error'):
                            print(line)
                    print('----------')
                    if cpe.returncode == 2:
                        print(f'Could not mux {mkv_path.name} in {mux_path}')
                        continue
            is_converted = True
            mkv_path = mux_path
            mkv_name = mkv_path.stem
            mux_path = first_available_path(output_path / mkv_name)
        else:
            mkv_name = mkv_path.name
            mux_path = first_available_path(output_path / mkv_name)

        with lock:
            print(f'Muxing {mkv_name} in {mux_path}... ')
        try:
            mux_mkv(mkv_path, subtitles, mux_path, mkvmerge_path)
        except CalledProcessError as cpe:
            with lock:
                print('----------')
                print('mkvmerge sent the following messages:')
                for line in cpe.stdout.splitlines():
                    if line.startswith('Warning') or line.startswith('Error'):
                        print(line)
                print('----------')
                if cpe.returncode == 2:
                    print(f'Could not mux {mkv_name} in {mux_path}')
                    continue
        except Exception:
            with lock:
                print('----------')
                print(f'An error occurred while muxing {mkv_name} in {mux_path}, skipping...')
                print_exc()
                print('----------')
            continue

        with lock:
            print(f'Done muxing {mkv_name} in {mux_path}')
            if is_converted:
                print(f'Removing {mkv_path}...')
                mkv_path.unlink()

def main(args, mkvmerge_path=None):
    if not mkvmerge_path:
        mkvmerge_path = 'mkvmerge'

    if not verify_mkvmerge(mkvmerge_path):
        print("Could not find mkvmerge, please add it to $PATH")
        return

    mux_queue = generate_mux_queue(args)
    total_operations = len(mux_queue)
    if total_operations == 0:
        return

    available_cores = cpu_count()
    num_workers = available_cores if available_cores <= total_operations else total_operations
    worker_operations, remaining_operations = divmod(total_operations, num_workers)
    lock = Lock()
    processes = []

    for _ in range(num_workers):
        worker_queue = []
        if len(mux_queue) >= worker_operations:
            additional_load = 0
            if remaining_operations:
                additional_load = 1
                remaining_operations -= 1
            num_operations = worker_operations + additional_load
            worker_queue = mux_queue[:num_operations]
            mux_queue = mux_queue[num_operations:]
        else:
            worker_queue = mux_queue
            mux_queue = []
        process = Process(target=worker, args=(worker_queue, lock, mkvmerge_path))
        processes.append(process)
        process.start()

    [process.join() for process in processes]

if __name__ == '__main__' and len(sys.argv) > 1:
    sigint_handler()
    main(sys.argv[1:])
