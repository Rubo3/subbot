from setuptools import setup, find_packages
from pathlib import Path

script_path = Path(__file__).parent.absolute()

long_description = (script_path / 'README.md').read_text()

setup(
    author="Marco Rubin",
    author_email="marco.rubin@protonmail.com",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
        "Topic :: Utilities"
    ],
    description="Automating subtitles management for lazy subbers.",
    # extras_require = {"dev": ["pytest"]},
    entry_points={"console_scripts": ["subbot=subbot.__main__:cli",]},
    install_requires=[
        "google-api-python-client >= 1.12.5",
        "google-auth-httplib2 >= 0.0.4",
        "google-auth-oauthlib >= 0.4.2",
        "mega.py >= 1.0.8",
        "PyInquirer-fork == 1.0.4",
        "pymkv >= 1.0.8",
        "rich >= 9.1.0"
    ],
    keywords="subtitles, mkv, ass",
    long_description=long_description,
    long_description_content_type="text/markdown",
    name="subbot",
    packages=find_packages(exclude=["docs", "tests"]),
    python_requires=">=3.8, <4",
    url="https://www.gitlab.com/Rubo/subbot",
    version="0.1.7",
)
