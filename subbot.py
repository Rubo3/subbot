from os.path    import isfile, isdir
from pathlib    import Path
import re
from shutil     import which
from signal     import SIGINT, signal
from subprocess import PIPE, Popen
from sys        import argv, stderr, stdout, exit as sysexit
from traceback  import print_exc

from pymkv      import identify_file, ISO639_2_languages, MKVFile, MKVTrack, verify_matroska

MKVMERGE_PATH = which('mkvmerge')

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
        elif arg in ('--output', '-o') and i + 1 < len(args) and isdir(args[i + 1]):
            if subtitles and videos:
                output_dir = args[i + 1]
                paths[Path(output_dir)] = {'subtitles': subtitles, 'videos': videos}
            subtitles = set()
            videos = set()
        elif Path(arg) not in paths:
            print(f"Unrecognised '{arg}', skipping...", file=stderr)
    if subtitles and videos:
        paths[Path.cwd()] = {'subtitles': subtitles, 'videos': videos}
    return paths

def make_mux_queue(paths):
    mux_queue = []
    for output_dir in paths:
        subtitles = paths[output_dir]['subtitles']
        videos = paths[output_dir]['videos']

        for video in videos:
            check_match = lambda sub: strip_properties(sub.stem) == video.stem
            association = {
                'video_path': video,
                'output_dir': output_dir,
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
    if len(splitted) == 1: # `filename` does not contain properties.
        return filename
    # The properties are in the last string, so we don't consider them here.
    return ' ['.join(splitted[:-1])

def first_available_path(path):
    copy_counter = 0
    stem = path.stem
    # Check if the path already contains a copy counter N of type ' (N)' at the end.
    counter_candidates = re.findall(r' \((\d+)\)$', stem)
    if counter_candidates:
        copy_counter += int(*counter_candidates)
        stem = ''.join(stem.rsplit(f' ({copy_counter})', 1)) # Remove the counter.
    while path.exists():
        copy_counter += 1
        path = path.parent / (stem + f' ({copy_counter})' + path.suffix)
    return path

def make_mkvmerge_command(video_path, subtitles_properties, output_path):
    mkv = MKVFile(video_path, mkvmerge_path=MKVMERGE_PATH)
    current_tracks = mkv.get_track()

    for subtitle_path in subtitles_properties:
        track_id = subtitles_properties[subtitle_path].pop('_track_id', 0)
        subtitle_track = MKVTrack(
            file_path=subtitle_path,
            mkvmerge_path=MKVMERGE_PATH,
            **subtitles_properties[subtitle_path]
        )

        if 0 <= track_id < len(current_tracks) \
        and current_tracks[track_id].track_type == 'subtitles':
            mkv.replace_track(track_id, subtitle_track)
            continue

        for track in current_tracks:
            if track.track_type == 'subtitles' \
            and track.track_name == subtitle_track.track_name:
                mkv.replace_track(track.track_id, subtitle_track)
                break
        else:
            mkv.add_track(subtitle_track)

    command = mkv.command(output_path, subprocess=True)
    # Add option to parse non-translated, `\n`-terminated (instead of `\r`) lines.
    command.insert(1, '--gui-mode')
    return command

# To be set by other users of `main`.
def show_progress(process, output_path):
    for line in process.stdout:
        if line.startswith(('#GUI#warning', '#GUI#error')):
            print(line[5:].title().strip(), file=stderr)

def merge(association):
    video_path = association['video_path']
    subtitles_properties = association['subtitles']
    output_dir = association['output_dir']
    output_path = first_available_path(output_dir / (video_path.stem + '.mkv'))

    try:
        command = make_mkvmerge_cmd(video_path, subtitles_properties, output_path)
    except Exception:
        print(f"While muxing '{video_path}' in '{output_path}' an exception occurred, skipping...",
              file=stderr)
        print_exc(file=stderr)
        return

    process = Popen(command, stdout=PIPE, text=True, bufsize=1)
    show_progress(process, str(output_path))
    returncode = process.wait()
    if returncode == 0:
        print(output_path)
    elif returncode == 2:
        print(f"Could not mux '{video_path}' in '{output_path}', skipping...", file=stderr)

def main(args):
    if len(args) < 2:
        print('Usage: subbot file1.vid file1.sub ... [--output dir]')
        return

    if MKVMERGE_PATH is None:
        print('Could not find `mkvmerge`, please add it to $PATH.')
        sysexit(1)

    paths = identify_files(args)
    mux_queue = make_mux_queue(paths)
    for association in mux_queue:
        merge(association)

if __name__ == '__main__':
    sigint_handler()
    main(argv[1:])
