from pathlib import Path
import socket

from PyInquirer.prompt import prompt

from subbot.utils.dictionaries import PathDict, defaultdict_factory, pathdict_factory, RecursiveDefaultDict
from subbot.utils.jsonutils import read_json_dict, write_json
from subbot.utils.misc import ask_directory, ask_filename, get_hash

class Config():
    def __init__(self, path=None, object_pairs_hook=defaultdict_factory):
        if not path:
            path = Path.cwd() / "config.json"
        self.config = read_json_dict(
            path,
            object_pairs_hook=object_pairs_hook,
            return_=PathDict
        )
        if "config_path" in self.config:
            self.path = self.config["config_path"]
            self.config = read_json_dict(
                self.path,
                object_pairs_hook=object_pairs_hook,
                return_=PathDict
            )
        else:
            self.path = path

    def get(self, key, default):
        try:
            return self.__getitem__(key)
        except:
            return default

    def save(self, indent = 2):
        write_json(obj=self.config, path=self.path, indent=indent)

    def __getitem__(self, key):
        return self.config.__getitem__(key)

    def __setitem__(self, key, value):
        return self.config.__setitem__(key, value)

class SubbotConfig(Config):
    def __init__(self, path):
        super().__init__(path=path, object_pairs_hook=pathdict_factory)

    def check(self):
        properties_path = self.config.get("properties_path", "")
        if not self.config.get("properties_hash", ""):
            self.config["properties_hash"] = get_hash(properties_path)

        if not self.config.get("projects", {}):
            self.config["projects"] = PathDict()

        if not self.config.get("output_path", ""):
            print("Select the directory where you want to temporarily store the new MKVs:")
            self.config["output_path"] = ask_directory()

        if not self.config.get("mux_queue", PathDict()):
            self.config["mux_queue"] = PathDict()

        if not self.config.get("move_queue", PathDict()):
            self.config["move_queue"] = PathDict()

        if not self.config.get("upload_queue", PathDict()):
            self.config["upload_queue"] = PathDict()

        if not self.config.get("reverse_upload_queue", PathDict()):
            self.config["reverse_upload_queue"] = PathDict()

        # temporary secrets path
        if not self.config.get("secrets_path", ""):
            print("Select the upload secrets directory:")
            self.config["output_path"] = ask_directory()

        if not self.config.get("path_index", ""):
            self.config["path_index"] = PathDict()

    def check_path(self, path):
        if isinstance(path, str):
            path = Path(path)

        # os_name = os.name # could be useful to better reduce edge-cases
        hostname = socket.gethostname()

        local_path = path

        if not path.exists():
            local_path = self.config.get("path_index", {}).get(path, {}).get(hostname, "")
            if not local_path:
                print(f"Please select the directory which corresponds to '{path}' on this computer:")
                local_path = ask_directory()
                self.config["path_index"][path][hostname] = local_path

        return local_path

    def update_upload_queue(self, mkv_name, upload_settings):
        upload_queue = self.config.get("upload_queue", PathDict())

        for storage_service in upload_settings:
            for account, path in upload_settings[storage_service].items():
                if path not in upload_queue[storage_service][account]:
                    upload_queue[storage_service][account][path] = []
                if mkv_name not in upload_queue[storage_service][account][path]:
                    upload_queue[storage_service][account][path].append(mkv_name)

    def __getitem__(self, key):
        """Standard `dict` method. Returns a pathlib.Path object
        if the last 5 characters of a `str` `key` are "_path".
        """

        value = self.config.__getitem__(key)
        if isinstance(value, str) and key[-5:] == "_path":
            return self.check_path(value)
        return value

def clean_upload_queue(upload_queue, storage_service = None, account = None, folder = None, mkv = None, answers = None):
    if storage_service and account and folder and mkv:
        if len(upload_queue[storage_service][account][folder]) > 1:
            try:
                upload_queue[storage_service][account][folder].remove(mkv)
            except ValueError:
                pass
        else:
            upload_queue[storage_service][account].pop(folder, "")
            if len(upload_queue[storage_service][account]) == 0:
                upload_queue[storage_service].pop(account, "")
            if len(upload_queue[storage_service]) == 0:
                upload_queue.pop(storage_service, "")
    elif answers:
        new_upload_queue = RecursiveDefaultDict()
        for answer in answers:
            first_bracket = answer.index('\u00a0(')
            mkv = answer[:first_bracket]
            storage_service, account, path = answer[first_bracket + 2:-1].split(",\u00a0")
            if not new_upload_queue[storage_service][account][path]:
                new_upload_queue[storage_service][account][path] = []
            new_upload_queue[storage_service][account][path].append(mkv)
            upload_queue = new_upload_queue

    return upload_queue

def first_run(config):
    question = {
        'type': 'rawlist',
        'name': 'config',
        'message': 'Do you want to create a new configuration file or import an existing one?',
        'choices': [
            'Create a new one.',
            'Import an existing one.',
        ]
    }

    print("Welcome to Subbot!")
    if prompt(question)["config"] == "Create a new one.":
        print("Please select the directory where you want to store it:")
    else:
        print("Please select the directory which contains `config.json`:")
    config_path = ask_directory() / "config.json"
    config["config_path"] = config_path
    config.save()

    return SubbotConfig(config_path)

def upload_question(upload_queue):
    """Generates the list of files to choose before uploading them.
    Every choice is a string in the form 'name (service account folder)'.
    Please note that the Unicode character 'U+00A0' (no-break space) is used to parse
    faster the returned strings, in order to get back the service, account and folder
    properties needed to reconstruct the upload queue.
    There could be, and surely are, better ways to do this.
    """
    choices = []
    for storage_service in upload_queue:
        for account in upload_queue[storage_service]:
            for path in upload_queue[storage_service][account]:
                for mkv in upload_queue[storage_service][account][path]:
                    choices.append({'name': mkv + '\u00a0(' + storage_service + ',\u00a0' + account + ',\u00a0' + path + ')'})
    question = {
        'type': 'checkbox',
        'message': 'Select files to upload:',
        'name': 'upload',
        'choices': choices
    }
    return question
