from fnmatch import filter as fnfilter, fnmatch
from glob import glob
from os import environ, listdir
from pathlib import Path
import sys

import yaml

from subbot import main, sigint_handler

def glob_pattern(patterns):
    matches = []
    if isinstance(patterns, str):
        patterns = [patterns,]
    for pattern in patterns:
        matches.extend(glob(pattern, recursive=True))
    return matches

def expand_args(args, config):
    expanded_args = []

    for arg in args:
        project_pattern, file_pattern = arg.split('/')
        matched_projects = fnfilter(config['projects'], project_pattern)
        if not matched_projects:
            print(f'No project matches the pattern in "{arg}"')
            continue
        project = matched_projects[0]
        check_match = lambda filepath: fnmatch(Path(filepath).name, file_pattern)

        subtitles = glob_pattern(config['projects'][project]['subtitles'])
        matched_subtitles = filter(check_match, subtitles)
        if not matched_subtitles:
            print(f'No subtitles found for "{arg}", skipping...')
            continue
        expanded_args.extend(matched_subtitles)

        videos = glob_pattern(config['projects'][project]['video'])
        matched_videos = filter(check_match, videos)
        if not matched_videos:
            print(f'No video found for "{arg}", skipping...')
            continue
        expanded_args.extend(matched_videos)

        output_path = ''
        # The per-project `output_path` has precedence over the global `output_path`,
        # the global `output_path` has precedence over the actual MKV path.
        if 'output_path' in config['projects'][project]:
            output_path = config['projects'][project]['output_path']
        elif 'output_path' in config:
            output_path = config['output_path']
        expanded_args.extend(['--output', output_path])

    return expanded_args

if __name__ == '__main__':
    sigint_handler()
    args = sys.argv[1:]
    if not args:
        print('Usage: subbotf proj*1/file1* ...')
        sys.exit(0)

    script_parent = Path(__file__).parent.absolute()
    if 'SUBBOTF_PROJECTS' in environ:
        projects = Path(environ['SUBBOTF_PROJECTS'])
    elif 'projects.yaml' in listdir(script_parent):
        projects = script_parent / 'projects.yaml'
    else:
        print(
            f'File `projects.yaml` not found, please add it in `{script_parent}`,'
             'or specify a file path in $SUBBOTF_PROJECTS',
            file=sys.stderr
        )
        sys.exit(1)

    with open(projects) as y:
        config = yaml.safe_load(y)

    if 'projects' not in config:
        print(f'No project found, please add at least one in {script_parent / "projects.yaml"}')
        sys.exit(2)

    expanded_args = expand_args(args, config)
    mkvmerge_path = config.get('mkvmerge_path', 'mkvmerge')
    main(expanded_args, mkvmerge_path)
