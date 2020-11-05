import argparse
import os
from pathlib import Path
import sys

from PyInquirer.prompt import prompt

from subbot.lib.main_functions import check_mkv_properties, check_projects, check_subtitles
from subbot.lib.config import clean_upload_queue, first_run, SubbotConfig, upload_question
from subbot.lib.main_functions import edit_subtitles_directories, update_subtitles, replace_subtitles, upload_mkv, move_mkv
from subbot.utils.misc import ask_directory, ask_filename
from subbot.lib.mkv import add_project, create_mkv_properties
from subbot.utils.dictionaries import PathDict, pathdict_factory
from subbot.utils.jsonutils import read_json_dict, write_json
from subbot.utils.misc import get_hash

def cli():
    try:
        script_path = Path(__file__).parent.absolute()
        config = SubbotConfig(path=script_path / "config.json")
        main(config)
    except KeyboardInterrupt:
        print("See you!")

def main(config = None, args_list = []):
    parser = argparse.ArgumentParser(description='automate subtitles management for lazy subbers')
    parser.add_argument('-m', '--manual', action='store_true', help='activate manual mode')
    if not args_list:
        args = parser.parse_args()
    else:
        parser.parse_args(args_list)

    if len(config.config) == 0:
        config = first_run(config)
    config.check()

    properties_path = config.get("properties_path", Path())
    if not properties_path or not properties_path.is_file():
        question = {
            'type': 'rawlist',
            'name': 'properties_file',
            'message': 'Do you want to create a new MKV properties file or import an existing one?',
            'choices': [
                'Create a new one.',
                'Import an existing one.',
            ]
        }
        if prompt(question)["properties_file"] == "Create a new one.":
            print("Please select the directory where you want to store it:")
        else:
            print("Please select the directory which contains `mkv_properties.json`:")
        properties_path = ask_directory() / "mkv_properties.json"
        config["properties_path"] = properties_path
    mkv_properties = read_json_dict(properties_path, object_pairs_hook=pathdict_factory)

    if not mkv_properties:
        mkv_properties = create_mkv_properties(properties_path)
    else:
        # Go through this pain only if the properties file has changed.
        properties_hash = get_hash(properties_path / "mkv_properties.json")
        if properties_hash != config.get("properties_hash", ""):
            print(f"Checking for changes in the MKV properties file...")
            config = check_mkv_properties(config, mkv_properties)
            config["properties_hash"] = properties_hash
            config.save()

    config = check_projects(config, mkv_properties)

    config, changes = check_subtitles(config)
    if not changes:
        print("No tracked subtitle has changed.")

    main_question = {
        'type': 'rawlist',
        'name': 'action',
        'message': 'What do you want to do?',
        'choices': [
            'Add a new project to the MKV properties.',
            'Edit tracked subtitles directories.',
            'Update the subtitles list but not their MKVs.',
            'Update the subtitles list and their MKVs.',
            'Upload MKVs (currently only Google Drive and MEGA are supported).',
            'Move MKVs into their directories.',
            'Exit.',
        ]
    }

    while True:
        action = prompt(main_question)["action"]

        mux_queue = config.get("mux_queue", PathDict())
        projects = config.get("projects", PathDict())

        if action == "Add a new project to the MKV properties.":
            mkv_properties = add_project(mkv_properties)
            config = check_projects(config, mkv_properties)
            write_json(mkv_properties, config["properties_path"])
            config.save()

        if action == "Edit tracked subtitles directories.":
            config["projects"] = edit_subtitles_directories(config["projects"])
            config.save()

        elif action == "Update the subtitles list but not their MKVs.":
            if len(mux_queue) == 0:
                print("There's nothing to do here.")
            else:
                projects = update_subtitles(mux_queue, projects)
                print("Cleaning up the mux queue... ", end="")
                mux_queue.clear()
                print("Done.")
                config.save()

        elif action == "Update the subtitles list and their MKVs.":
            if len(mux_queue) == 0:
                print("There's nothing to do here.")
            else:
                config = replace_subtitles(config, mkv_properties)
                config.save()

        elif action == "Upload MKVs (currently only Google Drive and MEGA are supported).":
            upload_queue = config.get("upload_queue", PathDict())
            output_path = config.get("output_path", Path())

            if args.manual:
                print("Updating upload queue with the new files... ", end="")
                mkv_list = [file_ for file_ in output_path.iterdir() if file_.is_file() and file_.suffix == ".mkv"]

                for mkv in mkv_list:
                    for project in mkv_properties:
                        if upload_settings := mkv_properties[project].get(mkv, PathDict()).get("upload", PathDict()):
                            config.update_upload_queue(mkv, upload_settings)
                config.save() # Is it really needed here?

            question = upload_question(upload_queue)
            if question["choices"]:
                answers = prompt(question)["upload"] # add a style
                upload_queue = clean_upload_queue(upload_queue, answers)
                secrets_path = config.get("secrets_path", Path())

                new_upload_queue = upload_mkv(upload_queue, secrets_path, output_path)

                config["upload_queue"] = new_upload_queue
                config.save()
            else:
                print("There are no files to upload.")

        elif action == "Move MKVs into their directories.":
            config = move_mkv(config)
            config.save()

        elif action == "Exit.":
            config.save()
            print("All right, see you!")
            break


if __name__ == '__main__':
    cli()
