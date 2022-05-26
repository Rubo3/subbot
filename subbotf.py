from fnmatch import filter as fnfilter, fnmatch
from glob    import glob
from os      import environ, listdir
from pathlib import Path
import re
from shutil  import which
from sys     import argv, stderr, exit as sysexit

from tqdm import tqdm
import yaml

import subbot

def glob_pattern(patterns):
    matches = []
    if isinstance(patterns, str):
        patterns = [patterns,]
    for pattern in patterns:
        matches.extend(glob(pattern, recursive=True))
    return matches

def expand_args(args, config):
    invocations = []

    for arg in args:
        if arg.count('/') != 1:
            print(f"Unrecognised '{arg}', skipping...")
            continue

        project_pattern, file_pattern = arg.split('/')
        matched_projects = fnfilter(config['projects'], project_pattern)
        if not matched_projects:
            print(f"No project matches the pattern in '{arg}'.")
            continue
        project = matched_projects[0]
        match_pattern = lambda filepath: fnmatch(Path(filepath).name, file_pattern)
        args = []

        videos = glob_pattern(config['projects'][project]['video'])
        matched_videos = filter(match_pattern, videos)
        if not matched_videos:
            print(f'No video associated to "{arg}", skipping...')
            continue
        args.extend(matched_videos)

        subtitles = glob_pattern(config['projects'][project]['subtitles'])
        matched_subtitles = filter(match_pattern, subtitles)
        if not matched_subtitles:
            print(f'No subtitles associated to "{arg}", skipping...')
            continue
        args.extend(matched_subtitles)

        output_path = ''
        # The per-project `output_path` has precedence over the global `output_path`,
        # the global `output_path` has precedence over the actual MKV path.
        if 'output_path' in config['projects'][project]:
            output_path = config['projects'][project]['output_path']
        elif 'output_path' in config:
            output_path = config['output_path']
        args.append(output_path)

        invocations.append(args)

    return invocations

def show_progress(process, mux_path):
    with tqdm(range(100), mux_path, leave=False, file=stderr,
              bar_format='{l_bar}{bar}|{elapsed}') as pbar:
        curr_percentage = 0
        last_percentage = 0
        for line in process.stdout:
            match = re.search('#GUI#progress (\\d+)%', line)
            if line.startswith(('#GUI#warning', '#GUI#error')):
                pbar.write(f'{line[5].upper()}{line[6:]}'.strip(), file=stderr)
            if match is None:
                continue
            curr_percentage = int(match.group(1))
            pbar.update(curr_percentage - last_percentage)
            last_percentage = curr_percentage
        if pbar.n == 0: # an error occurred
            pbar.clear()

def main(args):
    if not args:
        print('Usage: subbotf proj*1/file1* ...')
        return

    script_parent = Path(__file__).parent.absolute()
    if 'SUBBOTF_PROJECTS' in environ:
        projects = Path(environ['SUBBOTF_PROJECTS'])
    elif 'projects.yaml' in listdir(script_parent):
        projects = script_parent / 'projects.yaml'
    else:
        print(f"File 'projects.yaml' not found, please add it in '{script_parent}',"
               "or specify a file path in $SUBBOTF_PROJECTS.",
              file=stderr)
        sysexit(1)

    with open(projects) as y:
        config = yaml.safe_load(y)

    if 'projects' not in config:
        print(f"No project found, please add at least one in '{script_parent / 'projects.yaml'}'.")
        sysexit(2)

    invocations = expand_args(args, config)
    # MKVMERGE_PATH needs to be a non-empty string, otherwise subbot.verify_mkvmerge fails
    subbot.MKVMERGE_PATH = config.get('mkvmerge_path', 'mkvmerge')
    subbot.show_progress = show_progress
    for args in invocations:
        subbot.main(args)

if __name__ == '__main__':
    subbot.sigint_handler()
    args = argv[1:]
    main(args)
