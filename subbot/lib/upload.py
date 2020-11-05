import os
from pathlib import Path
import pickle

from googleapiclient.discovery import build
from googleapiclient.http import InvalidChunkSizeError, MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import mega

from subbot.lib.stdout import progressbar
from subbot.utils.jsonutils import read_json_dict

class GoogleDrive():
    def __init__(self, account, secrets_path):
        # If you modify these scopes, delete the .pickle file.
        SCOPES = [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive"
        ]

        if isinstance(secrets_path, str):
            secrets_path = Path(secrets_path)

        credentials_path = secrets_path / (account + '.pickle')
        credentials = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow is completed for the first time.
        if os.path.exists(credentials_path):
            with open(credentials_path, 'rb') as token:
                credentials = pickle.load(token)
        # If there are no valid credentials available, let the user log in.
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(secrets_path / 'credentials.json', SCOPES)
                credentials = flow.run_local_server(port=0)
            # Save the credentials for the next run.
            with open(credentials_path, 'wb') as token:
                pickle.dump(credentials, token)

        self.drive = build('drive', 'v3', credentials=credentials)

    def folder_request(self, folder_name):
        folders = self.drive.files().list(
            q=f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false",
            spaces='drive'
        ).execute().get('files', [])

        if not folders:
            folder_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            folder = self.drive.files().create(body=folder_metadata, fields="id").execute()
        else:
            # TODO: the query should be more specific,
            # as there could be more than one folder with the same name.
            folder = folders[0]

        self.folder = folder

    def file_request(self, file_path, folder_id = None, chunk_size = 256 * 1024, resumable = True):
        """Args:
            file_path (str or os.PathLike): absolute path of the file you want to upload.
            folder_id (int): id of the Google Drive folder where you want to upload your file.
            chunk_size (int, optional): size of the chunk in bytes. Defaults to 256*1024.
            resumable (bool, optional): Set to False if you don't want the upload to be resumable. Defaults to True.
        """

        if isinstance(file_path, (str, os.PathLike)):
            file_path = Path(file_path)
        else:
            raise TypeError("The file_path argument is not str or os.PathLike.")

        file_size = file_path.stat().st_size
        if file_size == 0:
            raise InvalidChunkSizeError()
        if file_size <= chunk_size:
            # The size is tiny, so the file is uploaded in one chunk.
            chunk_size = file_path.stat().st_size
        if not folder_id:
            folder_id = self.folder.get("id", None)
        self.chunk_size = chunk_size
        self.file_size = file_size

        # The 'parents' metadata can be modified only if the file doesn't already exist.
        metadata = {"name": file_path.name}
        media = MediaFileUpload(file_path, chunksize=chunk_size, resumable=resumable)

        files = self.drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive"
        ).execute().get("files", [])

        for queried_file in files:
            if queried_file.get("name", "") == file_path.name:
                return self.drive.files().update(
                    fileId=queried_file.get("id", None),
                    body=metadata,
                    media_body=media
                )
        else:
            metadata["parents"] = [folder_id]
            return self.drive.files().create(body=metadata, media_body=media)

    def upload(self, file_path):
        if isinstance(file_path, (str, os.PathLike)):
            file_path = Path(file_path)
        else:
            raise TypeError("The file_path argument is not str or os.PathLike.")

        file_request = self.file_request(file_path)
        update_task = progressbar.add_task(description="upload",
                                           filename=file_path.name,
                                           total=self.file_size)

        # If the size is tiny, the file will be uploaded in one chunk.
        percent = self.chunk_size
        remaining = self.file_size
        response = None
        with progressbar:
            while not response:
                status, response = file_request.next_chunk()
                if status:
                    progressbar.update(update_task, advance=percent)
                    remaining -= percent
            if not progressbar.finished:
                progressbar.update(update_task, advance=remaining)



class Mega():
    def __init__(self, account, secrets_path):
        if isinstance(secrets_path, (str, os.PathLike)):
            secrets_path = Path(secrets_path)
        else:
            raise TypeError("The secrets_path argument is not str or os.PathLike.")

        secrets = read_json_dict(secrets_path / 'mega.json')
        self.mega = mega.Mega().login(account, secrets[account])

    def folder_request(self, folder):
        self.folder = self.mega.find(folder, exclude_deleted=True)
        if not folder:
            self.folder = self.mega.create_folder(folder)

    def upload(self, file_path):
        if isinstance(file_path, (str, os.PathLike)):
            file_path = Path(file_path)
        else:
            raise TypeError("The file_path argument is not str or os.PathLike.")

        file_to_replace = self.mega.find(file_path.name, exclude_deleted=True)
        if file_to_replace:
            self.mega.destroy(file_to_replace)[0]

        # If the folder doesn't exist, mega_folder is None,
        # so the file is uploaded to the base folder.
        print(f"Uploading {file_path.name}... ", end="")
        self.mega.upload(file_path, self.folder[0] if self.folder else self.folder)
        print("Done.")



class StorageService():
    def __init__(self, storage_service, account, secrets_path):
        self.storage_service = storage_service
        self.account = account
        self.secrets_path = secrets_path

        if storage_service == "Google Drive":
            self.service = GoogleDrive(account, secrets_path)
        else:
            self.service = Mega(account, secrets_path)

    def folder_request(self, folder_name):
        self.service.folder_request(folder_name)

    def upload(self, file_path):
        self.service.upload(file_path)
