from copy import deepcopy
from pathlib import Path
import shutil
from subprocess import CalledProcessError
import traceback

from PyInquirer.prompt import prompt

from subbot.lib.config import clean_upload_queue
from subbot.lib.mkv import get_mkv_name, get_track_by_type, replace_subtitle
from subbot.lib.upload import StorageService
from subbot.utils.dictionaries import PathDict
from subbot.utils.misc import ask_directory, get_hash

def check_mkv_properties(config, mkv_properties):
    for project in mkv_properties:
        for path in mkv_properties[project]:
            config.check_path(path)

    return config

def add_subtitles_directory(project_name, project = None):
    if not project:
        project = PathDict()

    print(f"Select a directory which contains subtitles of {project_name}:")
    subtitles_folder = ask_directory()

    subtitles = [file_ for file_ in subtitles_folder.iterdir() if file_.is_file() and file_.suffix == '.ass']
    if subtitles:
        for subtitle in subtitles:
            project[subtitles_folder][subtitle.name] = get_hash(subtitle)
        print(f"The subtitles list of {project_name} has been updated.")
    else:
        print("There are no Advanced SubStation Alpha subtitles here...")

    return project

def edit_subtitles_directories(projects):
    main_question = {
        'type': 'rawlist',
        'name': 'action',
        'message': 'What do you want to do?',
        'choices': [
            'Track a new directory or overwrite an existing one.',
            'Update an existing directory.',
            'Remove an existing directory.',
            'Go back.'
        ]
    }

    while True:
        action = prompt(main_question)["action"]
        choices = [project for project in projects]
        question = {
            'type': 'rawlist',
            'message': 'Which project do you want to update?',
            'name': 'project',
            'choices': choices
        }

        if action == "Track a new directory or overwrite an existing one.":
            choice = prompt(question)["project"]
            new_project = add_subtitles_directory(project_name=choice)
            projects[choice].update(new_project)

        elif action == "Update an existing directory.":
            choice = prompt(question)["project"]
            projects[choice] = add_subtitles_directory(project_name=choice, project=projects[choice])

        elif action == "Remove an existing directory.":
            choice = prompt(question)["project"]
            sub_choices = [{'name': directory} for directory in projects[choice]]
            sub_question = {
                'type': 'checkbox',
                'choices': sub_choices,
                'message': 'Which directory do you want to remove?',
                'name': 'directory'
            }
            sub_answers = prompt(sub_question)["directory"]
            for answer in sub_answers:
                projects[choice].pop(answer)
                print(f"{answer} has been removed from {choice}")

        elif action == "Go back.":
            return projects

def check_projects(config, mkv_properties):
    question = {
        'type': 'confirm',
        'message': 'Do you want to add another directory?',
        'name': 'add_directory',
        'default': True,
    }
    projects = config.get("projects", PathDict())

    for project in mkv_properties:
        first_dir = True
        if not projects.get(project, PathDict()):
            while True:
                if first_dir:
                    first_dir = False
                elif not prompt(question)["add_directory"]:
                    break
                config["projects"][project] = add_subtitles_directory(project, config["projects"][project])
    return config

def check_subtitles(config):
    mux_queue = config.get("mux_queue", PathDict())
    projects = config.get("projects", PathDict())
    changes = False

    for project in projects:
        for subtitles_path in projects[project]:
            config_subtitles = projects[project][subtitles_path]
            local_subtitles_path = config.check_path(subtitles_path)
            local_subtitles = [file_.name for file_ in local_subtitles_path.iterdir() if file_.is_file() and file_.suffix == ".ass"]
            total_subtitles = set(config_subtitles.keys()).union(set(local_subtitles))

            for subtitle in total_subtitles:
                old_hash = projects[project][subtitles_path].get(subtitle, "")
                new_hash =  get_hash(local_subtitles_path / subtitle)

                if old_hash and new_hash and old_hash != new_hash:
                    changes = True
                    print(f"Found changes in {subtitle} ({old_hash} -> {new_hash}).")
                    mux_queue[project][subtitles_path][subtitle] = new_hash
                elif not old_hash and new_hash:
                    changes = True
                    mux_queue[project][subtitles_path][subtitle] = new_hash
                    print(f"Added {subtitle} of the project {project} to the mux queue.")
                elif old_hash and not new_hash:
                    changes = True
                    projects[project][subtitles_path].pop(subtitle, '')
                    print(f"Removed {subtitle} from {project} because it doesn't exist in {local_subtitles_path} anymore.")
    return config, changes

def update_subtitles(mux_queue, projects):
    try:
        for project in mux_queue:
            for subtitles_path in mux_queue[project]:
                for subtitle, subtitle_hash in mux_queue[project][subtitles_path].items():
                    if projects[project][subtitles_path].get(subtitle, ""):
                        print(f"Updating hash of {subtitle}... ", end="")
                    else:
                        print(f"Adding {subtitle} to the project {project}... ", end="")
                    projects[project][subtitles_path][subtitle] = subtitle_hash
                    print("Done.")
    except:
        traceback.print_exc()
    finally:
        return projects

def replace_subtitles(config, mkv_properties):
    mux_queue = config.get("mux_queue", PathDict())
    move_queue = config.get("move_queue", PathDict())
    upload_queue = config.get("upload_queue", PathDict())
    reverse_upload_queue = config.get("reverse_upload_queue", PathDict())
    output_path = config.get("output_path", Path())

    try:
        iterable_mux_queue = deepcopy(mux_queue)
        for project in iterable_mux_queue:
            for subtitles_path in iterable_mux_queue[project]:
                for subtitle in iterable_mux_queue[project][subtitles_path]:
                    subtitle_path = config.check_path(subtitles_path) / subtitle
                    mkv, tags = get_mkv_name(subtitle)

                    # Currently it searches only for the first path where it finds the MKV
                    for mkv_parent in mkv_properties[project]:
                        if mkv_properties[project][mkv_parent].get(mkv, ""):
                            break
                    else:
                        mkv_parent = ""

                    if mkv_parent:
                        default_tracks = mkv_properties[project][mkv_parent][mkv]['tracks']
                        default_track = get_track_by_type(default_tracks, 'subtitles', tags=tags)
                    else:
                        print(f"Couldn't find any property for {subtitle}. Skipping...")
                        continue
                    mkv_parent = config.check_path(mkv_parent)
                    mkv_path = mkv_parent / mkv

                    try:
                        replace_subtitle(subtitle_path, mkv_path, default_track, output_path, tags)
                    except CalledProcessError:
                        print(f"The `mkvmerge` command raised an error, leaving {subtitle} in the mux queue...")
                        continue

                    config['projects'][project][subtitles_path][subtitle] = mux_queue[project][subtitles_path][subtitle]
                    if len(mux_queue[project][subtitles_path]) > 1:
                        mux_queue[project][subtitles_path].pop(subtitle)
                    else:
                        mux_queue[project].pop(subtitles_path)
                    if len(mux_queue[project]) == 1:
                        mux_queue.pop(project)
                    print(f"The hash of {subtitle} has been updated.")

                    mkv_list = move_queue.get(project, {}).get(mkv_parent, [])
                    if not mkv_list:
                        move_queue[project][mkv_parent] = []
                    if mkv not in mkv_list:
                        move_queue[project][mkv_parent].append(mkv)
                        print(f"{mkv} has been added to the move queue.")

                    if not reverse_upload_queue.get(project, {}).get(mkv_parent, {}).get(mkv, ''):
                        upload_settings = mkv_properties[project][mkv_parent][mkv].get("upload", {})
                        if upload_settings:
                            upload_queue = config.update_upload_queue(mkv, upload_settings)
                            reverse_upload_queue[project][mkv_parent][mkv] = upload_settings
                            print(f"{mkv} has been added to the upload queue.")

                    if len(mux_queue[project]) > 1:
                        mux_queue[project].pop(subtitle, None)
                    else:
                        mux_queue.pop(project, None)
                    print(f"{subtitle} has been removed from the mux queue.")
    except:
        traceback.print_exc()
    finally:
        return config

def upload_mkv(upload_queue, secrets_path, output_path):
    chunk_size = 256*1024   # expressed in bytes

    try:
        iterable_upload_queue = deepcopy(upload_queue)
        for storage_service in iterable_upload_queue:
            for account in iterable_upload_queue[storage_service]:
                try:
                    service = StorageService(storage_service, account, secrets_path)
                except:
                    print("An error has occurred...")
                    traceback.print_exc()
                    print(f"Skipping {storage_service}...")
                    continue
                print(f"Uploading files to {storage_service} on {account}.")

                for folder in iterable_upload_queue[storage_service][account]:
                    service.folder_request(folder)
                    for mkv in iterable_upload_queue[storage_service][account][folder]:
                        mkv_path = output_path / mkv
                        try:
                            service.upload(mkv_path)
                            upload_queue = clean_upload_queue(upload_queue, storage_service, account, folder, mkv)
                            print(f"{mkv} has been uploaded and removed from the upload queue.")
                        except:
                            print("An error has occurred...")
                            traceback.print_exc()
                            print(f"Leaving {mkv} in the upload queue.")
    except:
        print("An error has occurred...")
        traceback.print_exc()
    finally:
        return upload_queue

def move_mkv(config):
    move_queue = config.get("move_queue", PathDict())
    upload_queue = config.get("upload_queue", PathDict())
    reverse_upload_queue = config.get("reverse_upload_queue", PathDict())
    output_path = config.get("output_path", Path())

    try:
        iterable_move_queue = deepcopy(move_queue)
        for project in iterable_move_queue:
            for mkv_parent in iterable_move_queue[project]:
                mkv_parent = config.check_path(mkv_parent)

                for mkv in iterable_move_queue[project][mkv_parent]:
                    print(f"Moving {mkv} in {mkv_parent}... ", end='')
                    mkv_path = mkv_parent / mkv

                    try:
                        shutil.move(src=output_path / mkv, dst=mkv_path)
                        upload_settings = reverse_upload_queue.get(project, PathDict()).get(mkv_parent, PathDict()).get(mkv, PathDict())
                        for storage_service in upload_settings:
                            for account in upload_settings[storage_service]:
                                online_path = upload_settings[storage_service][storage_service][account]
                                upload_queue = clean_upload_queue(upload_queue, storage_service, account, online_path, mkv)

                        move_queue[project][mkv_parent].remove(mkv)
                        print("Done.")
                    except:
                        print("An error has occurred...")
                        traceback.print_exc()
                        print(f"\nLeaving {mkv} in the move queue.")
            move_queue[project].pop(mkv_parent, {})
        move_queue.pop(project, {})
    except:
        traceback.print_exc()
    finally:
        return config
