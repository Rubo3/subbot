# `subbot`

`subbot` is a command-line tool aiming to automate the management of your subtitles, merging them into their video files with the properties you want. It is a wrapper around [`mkvmerge`](https://mkvtoolnix.download/doc/mkvmerge.html), a core tool of [MKVToolNix](https://mkvtoolnix.download).

It has no dependencies. A modified version of Sheldon Woodward's [pymkv](https://github.com/sheldonkwoodward/pymkv) is provided, which adds support for a custom `mkvmerge` executable path, lifts the restriction on MKV-only source files and removes its external dependencies. Currently `subbot` only works with Matroska video (MKV), QuickTime/MP4 and Advanced SubStation Alpha (ASS) files. The restriction is hard-coded: while in theory it should work with all the file formats supported by `mkvmerge`, tests need to prove it.

As it prints on the standard output only the path of the destination files, it designed to be composable with other programs, in the spirit of the Unix tradition. For example, its output can be piped to another program which uploads the files somewhere.

## How to use

`subbot` accepts as arguments a sequence of video and subtitle files you want to merge, in any order you want. After that, you can specify an optional directory, where the resulting videos will be put, otherwise the current working directory will be used. The command syntax is as follows:

```sh
python subbot.py file1.vid file1.sub ... [output_dir]
```

If a file with the same name as one of the new ones already exists in the output directory, a copy counter will be added to the new one before its extension (e.g. ` (1)`, ` (2)`, etc.), mirroring the behaviour of MKVToolNix.

In the `subbot` module, you can customise the `MKVMERGE_PATH` variable that is used to find the `mkvmerge` executable, and the `show_progress` function that is executed while `mkvmerge` is running. At the moment, the `show_progress` function accepts the [`Popen`](https://docs.python.org/3/library/subprocess.html#subprocess.Popen) object of the `mkvmerge` process currently running as its first argument, and the string of the destination file as its second. By default it shows the warnings and the errors found in the output of `mkvmerge`.

## How it works

The videos and the subtitles must share the same stem (the filename excluding the extension), except the subtitles filenames must also have the properties you want to embed into the tracks, written in any order after the stem, preceded by a whitespace (` `), enclosed by square brackets, one after the other, with no other characters between them. The supported properties are:

* the track id, an integer value which corresponds to the index of the track (default `0`);
* the track name, enclosed by apostrophes (`'`, default empty string);
* the track language, in [ISO 639-2](https://en.wikipedia.org/wiki/ISO_639-2) format (default `und`);
* the track being marked as `default` (default `False`);
* the track being marked as `forced` (default `False`).

For example, if you have a video named `example.mkv`, a subtitle corresponding to it would be `example.ass`, which would use the default values provided above for all those properties. Another one would be `example [2]['Test'][default][eng].ass`, which would force the track to replace the current third track, would be named `Test`, would be marked as `default` and its language would be set to `eng`. As a safety measure, a track will be replaced by a new one only if both are subtitle tracks, otherwise the latter will be appended.

## One more thing

Another script is provided, `subbotf`, which is an extension to `subbot` that aims to simplify the job even more, especially when you do it often and you have many projects to manage. It depends on [PyYAML](https://pypi.org/project/PyYAML/) and [tqdm](https://pypi.org/project/tqdm/) and needs a `projects.yaml` file (hence the `f` of "file" in `subbotf`), placed within the same directory of the script (a symbolic link suffices), or another YAML file whose absolute path is specified in the `$SUBBOTF_PROJECTS` environment variable (it has precedence over `projects.yaml`), structured like this (note the following are all the options available):

```yaml
projects:
    ArbitraryProjectName1:
        subtitles: /path/to/project/subtitles/*.ass
        videos: /path/to/project/videos/*.mkv
    ArbitraryProjectNameN:
        videos: /path/to/other/project/videos/[glob]*.mkv
        subtitles:
            - /path/to/other/project/subtitles/[gl]*.ass
            - /path/to/other/project/subtitles/[ob]*.ass
        output_path: /project-specific/output/path
mkvmerge_path: /custom/mkvmerge/path
output_path: /global/output/path
```

Your projects reside in the `projects` entry, and every project has its own `subtitles` and `videos`, specified through the use of [globbing](https://en.wikipedia.org/wiki/Glob_(programming)) with one pattern, as in the first project, or with a list of patterns, as in the second project's `subtitles`. You can also specify a custom `mkvmerge` command path, if it's not in your `PATH` environment variable, and a global or per-project `output_path`, with the latter having precedence over the former, and the former having precedence over the current working directory.

The command syntax is as follows:

```sh
python subbotf.py proj*1/file1* ...
```

Every argument consists of a glob of a project name (e.g. `proj*1`), separated by a slash (`/`), and a glob of the videos and subtitles files you want to merge (e.g. `file1*`). The script then matches the files with the pattern you have specified, checks whether they are tracked in their respective project in `projects.yaml`, then generates the appropriate arguments and passes them to `subbot`. If an argument does not contain exactly one `/`, it will be not recognised and therefore will be skipped.

When `mkvmerge` is running, a `tqdm` progress bar shows the current percentage of the process completion.

## Contribution

All contributions are welcome! If you want to help, please open a new issue, so that we can discuss about it.

## Possible ideas

* Add the `--mkvmerge` and `-m` arguments, possibly using the standard `argparse` module, to modify the `mkvmerge` executable path.
* Add support for the [other separators](https://gitlab.com/mbunkus/mkvtoolnix/-/wikis/Detecting-track-language-from-filename) in the function `get_properties`.
* Do not limit to videos and subtitles only.
* Make use of `swap_tracks`, `move_track`, etc. in the function `make_mkvmerge_command`.

## License

This software is free and open-source and distributed under the MIT License.
