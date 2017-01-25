from __future__ import unicode_literals

import os

from setuptools import setup

PACKAGE_PATH = os.path.abspath(os.path.dirname(__file__))


def get_description():
    with open(os.path.join(PACKAGE_PATH, "README")) as readme:
        return readme.read()


def get_requirements():
    requirements = []
    path = os.path.join(PACKAGE_PATH, "requirements.txt")

    with open(path) as requirements_txt:
        for requirement in requirements_txt:
            requirement = requirement.strip()
            if requirement and not requirement.startswith("#"):
                requirements.append(requirement)

    return requirements


if __name__ == "__main__":
    setup(
        name="git-backup",
        version="0.1.2",

        description="Script for backing up GitHub repositories",
        long_description=get_description(),
        url="https://github.com/KonishchevDmitry/git-backup",

        license="GPL3",
        author="Dmitry Konishchev",
        author_email="konishchev@gmail.com",

        classifiers=[
            "Development Status :: 4 - Beta",
            "Environment :: Console",
            "Intended Audience :: Developers",
            "Intended Audience :: System Administrators",
            "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
            "Natural Language :: English",
            "Operating System :: MacOS",
            "Operating System :: POSIX :: Linux",
            "Programming Language :: Python :: 2",
            "Programming Language :: Python :: 3",
            "Topic :: Software Development :: Version Control",
            "Topic :: System :: Archiving :: Backup",
            "Topic :: System :: Archiving :: Mirroring",
            "Topic :: Utilities",
        ],
        platforms=["linux", "osx"],

        install_requires=get_requirements(),
        py_modules=["git_backup"],
        entry_points={"console_scripts": ["git-backup = git_backup:main"]},
    )
