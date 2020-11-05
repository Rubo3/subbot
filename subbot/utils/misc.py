from hashlib import md5
import os
from pathlib import Path
from time import time
from tkinter import Tk, filedialog

class Timer():
    """A simple timer meant to be used with a context manager.
    """

    def __enter__(self):
        """Start a new timer."""
        self.start = time()
        return self

    def __exit__(self, *exc_info):
        """Stop the timer."""
        self.stop = time()
        print(f'Elapsed time: {self.stop - self.start}')



# Even if the file name changes, its hash doesn't
def get_hash(file_path):
    try:
        with open(file_path, 'rb') as f:
            file_read = f.read()
            return md5(file_read).hexdigest()
    except:
        return ''

# TODO: secondo me si può anche rimuovere, kennedyci?
def check_hash(path1, path2):
    if path1.is_file() and path2.is_dir():
        path2 = path2 / path1.name
    elif path1.is_dir() and path2.is_file():
        path1 = path1 / path2.name

    try:
        return get_hash(path1) == get_hash(path2)
    except:
        return False


def _ask_filedialog(func, **kwargs):
    root = Tk()
    root.withdraw()

    path = func(**kwargs)

    root.quit()

    return Path(path) if len(path) != 0 else Path.cwd()

def ask_filename():
    return _ask_filedialog(filedialog.askopenfilename)

def ask_directory():
    return _ask_filedialog(filedialog.askdirectory, mustexist=True)

if __name__ == "__main__":
    pass
