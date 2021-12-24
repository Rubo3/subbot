# `subbot`

`subbot` is a simple, self-contained, command-line tool which helps you automate the last part of subtitles management, lifting from you the burden of merging them into their video files with the properties you want.

A modified version of Sheldon Woodward's [pymkv](https://github.com/sheldonkwoodward/pymkv) is provided, which adds support for a custom `mkvmerge` binary path, lifts the restriction on MKV-only source files and removes its external dependencies. Currently `subbot` works with Matroska video (MKV), QuickTime/MP4 and Advanced SubStation Alpha (ASS) source files only. The restriction is hard-coded: while in theory it should work with all the file types supported by `mkvmerge`, tests need to be done to prove it.

As it prints in the standard output only the path of the muxed (destination) file, it is composable with other programs, in the spirit of the Unix tradition. For example, its output can be piped to another program which uploads the muxed files somewhere.

## How to use

You have to pass it at least two paths of the videos and the subtitles you want to merge, in any order you want. Then, you can specify an optional directory path with `--output` or `-o`, where all the new video files will be multiplexed. The syntax is as follows:

```sh
python subbot.py file1.vid file1.sub ... [--output dir]
```

If you don't specify an output directory path, the source video parent directory will be used, and a new video file will be created inside it. If a video file with the same name as the new one already exists within the output directory, a copy counter will be added to the new one before its extension (e.g. ` (1)`, ` (2)`, etc.), as MKVToolNix does.

You can specify multiple sequences of files followed by an optional output directory. For example, running:

```sh
python subbot.py \
    ~/path1/*.mkv ~/path3/*.ass ~/path2/*.mkv --output ~/path4 \
    ~/path5/*.mkv ~/path6/*.ass
```

will merge in `~/path4` the the files matched in `~/path1`, `~/path2` and `~/path3`, while the files matched in `~/path5` and `~/path6` will be merged in `~/path5`, as no output path was specified. Please note that if you want to merge your files inside their source directories, you have to specify them after the last optional output path, or you have not to specify an output path at all.

A `main` function is available to customise the arguments, the `mkvmerge` path and the `show_progress` function to execute while `mkvmerge` is running. At the moment, the `show_progress` function accepts the `Popen` process object as its first argument, and the string of the being-muxed (destination) file as its second, as these are the objects needed by `subbotf` to show a progress bar (see *[One more thing](#One-more-thing)*).

## How it works

It makes the assumption that the videos and the subtitles share the same stem (the file name excluding the extension), except the subtitles filenames also have the properties you want to embed into the tracks, written in any order just before their extension, one after the other, enclosed by square brackets, with no other characters between them, and this block is preceded by a space (` `). The supported properties are:

* the track id, an integer value which corresponds to the index of the track (default `0`);
* the track name, enclosed by apostrophes (`'`, default empty string);
* the track language, in [ISO 639-2](https://en.wikipedia.org/wiki/ISO_639-2) format (default `und`);
* the track being marked as `default` (default `False`);
* the track being marked as `forced` (default `False`).

I think an example speaks for itself: if you have a video named `example.mkv`, a subtitle corresponding to it would be `example.ass`, which would use the default values provided above for all those properties. Another one would be `example [2]['Test'][default][eng].ass`, which would force the track to replace the current third track, would be named `Test`, would be marked as `default` and its language would be set to `eng`. As a safety measure, a track will be replaced by a new one only if both are subtitle tracks, otherwise the latter will be appended.

## One more thing

I've provided another script, `subbotf.py`, which is an extension to `subbot` that aims to simplify the job even more, especially when you do it often and you have many projects to manage. It depends on [PyYAML](https://pypi.org/project/PyYAML/) and [tqdm](https://pypi.org/project/tqdm/) and needs a `projects.yaml` file (hence the `f` of "file" in `subbotf`), placed within the same directory of the script, or another YAML file whose absolute path is specified in the `$SUBBOTF_PROJECTS` environment variable (it has precedence over `projects.yaml`), structured like this (note the following are all the options available):

```yaml
projects:
    Project1:
        subtitles: /path/to/project/subtitles/*.ass
        videos: /path/to/project/videos/*.mkv
    ProjectN:
        videos: /path/to/other/project/videos/[glob]*.mkv
        subtitles:
            - /path/to/other/project/subtitles/[gl]*.ass
            - /path/to/other/project/subtitles/[ob]*.ass
        output_path: /project-specific/output/path
mkvmerge_path: /custom/mkvmerge/path
output_path: /global/output/path
```

Your projects reside in the `projects` dictionary, and every project has its own `subtitles` and `videos`, specified through the use of [globbing](https://en.wikipedia.org/wiki/Glob_(programming)) with one pattern, as in `Project1`, or with a list of patterns, as in `ProjectN`'s `subtitles`. You can also specify a custom `mkvmerge` command path, if it's not in your `$PATH`, a global output path and a per-project output path, with the latter having precedence over the first one, and the first one having precedence over the source video directory.

The command syntax is as follows:

```sh
python subbotf.py proj*1/file1* ...
```

Every argument consists of a glob of a project's name (`proj*1`), separated by a slash (`/`), and a glob of the videos and subtitles files you want to merge. The script then matches the files with the pattern you have specified, checks whether they are tracked in their respective project in `projects.yaml`, then generates the appropriate arguments and passes them to `subbot`. If an argument does not contain exactly one `/`, it will be not recognised and therefore will be skipped.

As a nice touch, when `mkvmerge` is running, a `tqdm` progress bar shows the current percentage of the process' completion.

## Contribution

All contributions are welcome! If you want to help, please open a new issue, so that we can discuss about it.

## License

This software is free and open-source and distributed under the MIT License.
