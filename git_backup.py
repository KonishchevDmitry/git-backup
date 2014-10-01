"""Creates a mirror of your GitHub repositories that is suitable for incremental backup."""

from __future__ import unicode_literals

import argparse
import errno
import logging
import os
import re
import shutil
import signal
import stat
import sys

import pcli.log
import psh
import psys.daemon
import requests

from psys import eintr_retry

log = logging.getLogger("git-backup")

_LOCK_FILE_NAME = ".lock"


class Error(Exception):
    def __init__(self, *args, **kwargs):
        message, args = args[0], args[1:]
        super(Error, self).__init__(
            message.format(*args, **kwargs) if args or kwargs else message)


def main():
    try:
        _configure_signal_handling()

        args = _parse_args()
        backup_dir = args.backup_dir

        pcli.log.setup(
            name="git-backup", debug_mode=args.debug,
            level=logging.WARNING if not args.debug and args.cron else None)

        _check_backup_dir(backup_dir)

        lock_file_path = os.path.expanduser(os.path.join(backup_dir, _LOCK_FILE_NAME))

        try:
            lock_file_fd = psys.daemon.acquire_pidfile(lock_file_path)
        except psys.daemon.PidFileLockedError as e:
            if args.cron:
                log.debug("Exiting: %s", e)
            else:
                raise Error("{}", e)
        except psys.daemon.PidFileLockError as e:
            raise Error("{}", e)
        else:
            try:
                _backup(args.user, backup_dir)
            finally:
                try:
                    os.unlink(lock_file_path)
                except EnvironmentError as e:
                    log.error("Failed to delete lock file '%s': %s.", lock_file_path, e)
                finally:
                    eintr_retry(os.close)(lock_file_fd)
    except Error as e:
        sys.exit("Error: {}".format(e))


def _check_backup_dir(backup_dir):
    for forbidden_dir in "/", os.path.expanduser("~"):
        try:
            forbidden = os.path.samefile(backup_dir, forbidden_dir)
        except EnvironmentError as e:
            if e.errno != errno.ENOENT:
                raise Error("Failed to check '{}' backup directory against '{}': {}.", backup_dir, forbidden_dir, e)
        else:
            if forbidden:
                raise Error("Invalid backup directory '{}': it mustn't be / or your home directory "
                            "because this script deletes all contents of the backup directory.", backup_dir)


def _backup(user, backup_dir):
    repositories = sorted(_get_user_repositories(user), key=lambda name: name.lower())

    if repositories:
        log.info("User %s has %s repositories: %s.", user, len(repositories), ", ".join(repositories))

        name_re = re.compile(r"^[a-zA-Z0-9_-][a-zA-Z0-9._-]*")
        for name in repositories[:]:
            if name_re.search(name) is None:
                log.error("Got an invalid repository name: '%s'. Ignore it.", name)
                repositories.remove(name)
    else:
        log.info("User %s doesn't have any repositories.", user)

    _cleanup(backup_dir, repositories)

    for name in repositories:
        url = "https://github.com/{user}/{name}.git".format(user=user, name=name)
        _mirror_repo(name, url, backup_dir)


def _cleanup(backup_dir, repositories):
    try:
        files = os.listdir(backup_dir)
    except EnvironmentError as e:
        raise Error("Unable to list '{}' directory: {}.", backup_dir, e)

    cleanup_files = set(files) - set(repositories) - {_LOCK_FILE_NAME}

    for file_name in cleanup_files:
        path = os.path.join(backup_dir, file_name)

        if file_name.startswith("."):
            log.debug("Removing '%s'.", path)
        else:
            log.warning("Remove deleted repository '%s'.", file_name)

        _rm_path(path)


def _rm_path(path):
    def log_error(error_path, error):
        log.error("Failed to remove '%s': %s.".format(error_path, error))

    try:
        if stat.S_ISDIR(os.lstat(path).st_mode):
            shutil.rmtree(path, onerror=lambda func, path, excinfo: log_error(path, excinfo[1]))
        else:
            os.unlink(path)
    except EnvironmentError as e:
        log_error(path, e)


def _get_user_repositories(user):
    repos = set()
    max_pages = 100
    url = "https://api.github.com/users/{user}/repos".format(user=user)

    for page in range(1, max_pages + 1):
        try:
            response = requests.get(url, params={"page": page}, timeout=30)
            if response.status_code != requests.codes.ok:
                raise Error(response.reason)

            try:
                if response.headers.get("Content-Type") == "application/json":
                    raise ValueError

                repos_info = response.json()
                if not isinstance(repos_info, list):
                    raise ValueError
            except ValueError:
                raise Error("Server returned an invalid response.")
        except (requests.RequestException, Error) as e:
            raise Error("Failed to get a list of user repositories from {}: {}", url, e)

        if not repos_info:
            break

        repos.update(repo_info["name"] for repo_info in repos_info)
    else:
        log.error("Got too many repositories from {} (>{} pages). Skip the rest of pages.", url, page)

    return list(repos)


def _mirror_repo(name, url, backup_dir):
    backup_path = os.path.join(backup_dir, name)
    temp_path = os.path.join(backup_dir, "." + name)

    if os.path.exists(backup_path):
        log.info("Syncing %s...", name)

        try:
            _git("-C", backup_path, "fetch")
        except psh.ExecutionError as e:
            log.error("Failed to sync %s repository: %s.", name, e)
    else:
        log.info("Mirroring %s...", name)

        try:
            _git("clone", "--mirror", url, temp_path)
            _git("-C", temp_path, "gc", "--aggressive")

            try:
                os.rename(temp_path, backup_path)
            except EnvironmentError as e:
                raise Error("Unable to rename '{}' to '{}': {}.", temp_path, backup_path, e)
        except (psh.ExecutionError, Error) as e:
            log.error("Failed to mirror %s: %s.", name, e)


def _git(*args):
    process = psh.sh.git(*args)

    try:
        process.execute()
    except BaseException as error:
        try:
            process.wait(check_status=False, kill=signal.SIGTERM)
        except psh.InvalidProcessState:
            pass

        raise error


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Creates a mirror of your GitHub repositories that is suitable for incremental backup.")
    parser.add_argument("user", help="GitHub user name")
    parser.add_argument("backup_dir", help="directory to backup the repositories to")
    parser.add_argument("--cron", action="store_true", help="cron mode")
    parser.add_argument("-d", "--debug", action="store_true", help="debug mode")
    args = parser.parse_args()

    if re.search(r"^[a-zA-Z0-9._-]+", args.user) is None:
        parser.error("Invalid user name.")

    args.backup_dir = os.path.abspath(args.backup_dir)

    return args


def _configure_signal_handling():
    state = {"terminating": False}

    def terminate(signum, frame):
        if not state["terminating"]:
            state["terminating"] = True
            sys.exit("The program has been terminated.")

    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGQUIT, terminate)


if __name__ == "__main__":
    main()
