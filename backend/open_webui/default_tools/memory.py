"""
title: memory
description: Persistent file storage. WORKFLOW FOR UPLOADED FILES: STEP 1 = store_import(import_all=True), STEP 2 = store_uploads_to_storage(src="filename", dest="filename"). NEVER skip step 1! Reading files: store_storage_exec(cmd="cat", args=["file"]). Writing files: store_storage_write(path="file", content="..."). Help: store_help()
author: Claude
version: 2.4.1
license: MIT
required_open_webui_version: 0.4.0

SETUP INSTRUCTIONS:
==================
For this tool to work properly, you must enable Native Function Calling:

Option 1 - Per Model (recommended):
  Admin Panel > Settings > Models > [Select Model] > Advanced Parameters > Function Calling > "Native"

Option 2 - Per Chat:
  Chat Controls (⚙️ icon) > Advanced Params > Function Calling > "Native"
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from open_webui.env import DATA_DIR

# =============================================================================
# CONFIGURATION (Valves)
# =============================================================================


class Valves(BaseModel):
    """Tool configuration via Open WebUI interface."""

    storage_base_path: str = Field(
        default_factory=lambda: str((DATA_DIR / "user_files" / "users").resolve()),
        description="User storage root path",
    )
    quota_per_user_mb: int = Field(default=1000, description="Quota per user in MB")
    max_file_size_mb: int = Field(default=300, description="Max file size in MB")
    lock_max_age_hours: int = Field(
        default=24, description="Max lock duration before expiration"
    )
    exec_timeout_default: int = Field(
        default=30, description="Default command timeout (seconds)"
    )
    exec_timeout_max: int = Field(
        default=300, description="Maximum allowed timeout (seconds)"
    )


# =============================================================================
# WHITELISTS
# =============================================================================

# Read-only commands (Uploads)
WHITELIST_READONLY = {
    # Reading
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "nl",
    "wc",
    "stat",
    "file",
    "du",
    "tac",
    # Navigation
    "ls",
    "tree",
    "find",
    # Text search
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "awk",
    "sed",
    # Text transformation
    "sort",
    "uniq",
    "cut",
    "paste",
    "tr",
    "fold",
    "fmt",
    "column",
    "rev",
    "shuf",
    "expand",
    "unexpand",
    "pr",
    # Join
    "join",
    # Comparison
    "diff",
    "diff3",
    "cmp",
    "comm",
    # Archives (list)
    "tar",
    "unzip",
    "zipinfo",
    "7z",
    # Compression (stdout)
    "zcat",
    "bzcat",
    "xzcat",
    # Checksums
    "md5sum",
    "sha1sum",
    "sha256sum",
    "sha512sum",
    "b2sum",
    "cksum",
    # Encoding
    "base32",
    "base64",
    "basenc",
    # Binary/Hex
    "strings",
    "od",
    "hexdump",
    "xxd",
    # JSON/XML/YAML
    "jq",
    "xmllint",
    "yq",
    # Encoding conversion (stdout)
    "iconv",
    # Calculation
    "bc",
    "dc",
    "expr",
    "factor",
    "numfmt",
    # Paths
    "basename",
    "dirname",
    "realpath",
    # Misc
    "echo",
    "printf",
    # Media (info reading)
    "ffprobe",
    "identify",
    "exiftool",
    # Database
    "sqlite3",
}

# Read/write commands (Storage, Documents)
WHITELIST_READWRITE = WHITELIST_READONLY | {
    # Additional reading
    "df",
    "locate",
    "which",
    "whereis",
    # Split
    "split",
    "csplit",
    # Additional comparison
    "sdiff",
    "patch",
    "colordiff",
    # Archives (extraction/creation)
    "zip",
    "7za",
    # Compression
    "gzip",
    "gunzip",
    "bzip2",
    "bunzip2",
    "xz",
    "unxz",
    "lz4",
    "zstd",
    # Additional checksums
    "sum",
    # Additional encoding
    "uuencode",
    "uudecode",
    # File modification
    "touch",
    "mkdir",
    "rm",
    "rmdir",
    "mv",
    "cp",
    "ln",
    "truncate",
    "mktemp",
    "install",
    "shred",
    "rename",
    # Permissions
    "chmod",
    # Document conversion
    "pandoc",
    # Encoding conversion
    "dos2unix",
    "unix2dos",
    "recode",
    # Additional calculation
    "seq",
    # Date/Time
    "date",
    "cal",
    # Additional paths
    "readlink",
    "pathchk",
    "pwd",
    # System (info)
    "uname",
    "nproc",
    "printenv",
    "env",
    # Control
    "timeout",
    "sleep",
    # Misc
    "yes",
    "tee",
    "xargs",
    "envsubst",
    "gettext",
    "tsort",
    "true",
    "false",
    # Media
    "ffmpeg",
    "magick",
    "convert",
    # Versioning
    "git",
}

# Allowed Git subcommands
GIT_WHITELIST_READ = {
    "status",
    "log",
    "show",
    "diff",
    "branch",
    "tag",
    "blame",
    "ls-files",
    "ls-tree",
    "shortlog",
    "reflog",
    "describe",
    "rev-parse",
    "rev-list",
    "cat-file",
}

GIT_WHITELIST_WRITE = {
    "add",
    "commit",
    "reset",
    "restore",
    "checkout",
    "rm",
    "mv",
    "revert",
    "cherry-pick",
    "stash",
    "clean",
}

GIT_BLACKLIST = {
    "push",
    "pull",
    "fetch",
    "clone",
    "remote",
    "gc",
    "prune",
    "filter-branch",
}

# Forbidden commands
BLACKLIST_COMMANDS = {
    # Interpreters/Shells
    "bash",
    "sh",
    "zsh",
    "fish",
    "dash",
    "csh",
    "tcsh",
    "ksh",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "php",
    "lua",
    "exec",
    "eval",
    "source",
    # Background / Fork
    "nohup",
    "disown",
    "setsid",
    "screen",
    "tmux",
    "at",
    "batch",
    "crontab",
    # System privileges
    "sudo",
    "su",
    "doas",
    "chown",
    "chgrp",
    # Network
    "wget",
    "curl",
    "fetch",
    "ssh",
    "scp",
    "sftp",
    "rsync",
    "nc",
    "netcat",
    "ncat",
    "telnet",
    "ftp",
    "ping",
    "traceroute",
    # System / Dangerous
    "dd",
    "mount",
    "umount",
    "kill",
    "killall",
    "pkill",
    "reboot",
    "shutdown",
    "halt",
    "poweroff",
    "systemctl",
    "service",
    "mkfs",
    "fdisk",
    "parted",
    "iptables",
    "firewall-cmd",
}

# Pattern to detect dangerous arguments
DANGEROUS_ARGS_PATTERN = re.compile(r"[;&|`$\n\r]|&&|\|\||>>|<<|>\s|<\s|\$\(|\$\{")


# =============================================================================
# ERRORS
# =============================================================================


class StorageError(Exception):
    """Base storage error."""

    def __init__(self, code: str, message: str, details: dict = None, hint: str = None):
        self.code = code
        self.message = message
        self.details = details or {}
        self.hint = hint
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "success": False,
            "error": self.code,
            "message": self.message,
            "details": self.details,
            "hint": self.hint,
        }


# =============================================================================
# MAIN CLASS
# =============================================================================


class Tools:
    def __init__(self):
        self.valves = Valves()
        self._commands_cache = None

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _get_user_root(self, __user__: dict) -> Path:
        """Returns the user's root directory."""
        user_id = __user__.get("id", "anonymous")
        return Path(self.valves.storage_base_path) / user_id

    def _get_conv_id(self, __metadata__: dict) -> str:
        """Returns the conversation ID."""
        return __metadata__.get("chat_id", "unknown")

    def _resolve_chroot_path(self, base: Path, relative_path: str) -> Path:
        """
        Resolves a relative path within a chroot and verifies it doesn't escape.
        Raises PATH_ESCAPE if escape attempt detected.
        """
        # Clean the path
        relative_path = relative_path.lstrip("/")

        # Resolve
        target = (base / relative_path).resolve()
        base_resolved = base.resolve()

        # Verify we stay in chroot
        try:
            target.relative_to(base_resolved)
        except ValueError:
            raise StorageError(
                "PATH_ESCAPE",
                f"Chroot escape attempt detected",
                {"path": relative_path, "chroot": str(base)},
                "Use only relative paths without ../",
            )

        return target

    def _validate_relative_path(self, path: str) -> str:
        """
        Validates that a relative path contains no traversal.
        Returns the cleaned path.
        """
        # Clean
        path = path.lstrip("/")

        # Block absolute paths
        if path.startswith("/"):
            raise StorageError(
                "PATH_ESCAPE",
                "Absolute paths forbidden",
                {"path": path},
                "Use only relative paths",
            )

        # Block .. that escapes current directory
        # Virtually resolve the path to check
        parts = []
        for part in path.split("/"):
            if part == "..":
                if not parts:
                    raise StorageError(
                        "PATH_ESCAPE",
                        "Directory escape attempt",
                        {"path": path},
                        "Paths with .. going too high are forbidden",
                    )
                parts.pop()
            elif part and part != ".":
                parts.append(part)

        return "/".join(parts) if parts else ""

    def _validate_command(self, cmd: str, whitelist: set, args: list = None) -> None:
        """Validates that a command is allowed."""
        if cmd in BLACKLIST_COMMANDS:
            raise StorageError(
                "COMMAND_FORBIDDEN",
                f"Command '{cmd}' is forbidden",
                {"command": cmd},
                "See store_help() for allowed commands",
            )

        if cmd not in whitelist:
            raise StorageError(
                "COMMAND_FORBIDDEN",
                f"Command '{cmd}' is not in whitelist",
                {"command": cmd, "allowed": sorted(list(whitelist))[:20]},
                "Use store_allowed_commands() to see available commands",
            )

        # If git, validate subcommands
        if cmd == "git" and args is not None:
            self._validate_git_command(args)

    def _validate_args(self, args: list, readonly: bool = False) -> None:
        """Validates arguments to detect injections."""
        for arg in args:
            arg_str = str(arg)

            # Check dangerous patterns
            if DANGEROUS_ARGS_PATTERN.search(arg_str):
                raise StorageError(
                    "ARGUMENT_FORBIDDEN",
                    f"Dangerous argument detected",
                    {"argument": arg_str},
                    "Characters ; | & && || > >> < << $( ${ ` are forbidden",
                )

            # In readonly mode, forbid -i (in-place) for sed
            if readonly and arg_str == "-i":
                raise StorageError(
                    "ARGUMENT_FORBIDDEN",
                    "Option -i (in-place) is forbidden in read-only mode",
                    {"argument": arg_str},
                    "This zone is read-only",
                )

    def _validate_path_args(self, args: list, chroot: Path) -> list:
        """
        Validates that arguments don't allow escaping the chroot.
        Blocks: absolute paths and .. that escape chroot.
        """
        chroot_resolved = chroot.resolve()

        for arg in args:
            arg_str = str(arg)

            # Block absolute paths
            if arg_str.startswith("/"):
                raise StorageError(
                    "PATH_ESCAPE",
                    "Absolute paths forbidden",
                    {"path": arg_str},
                    "Use only relative paths",
                )

            # Verify .. doesn't escape chroot
            if ".." in arg_str:
                try:
                    target = (chroot / arg_str).resolve()
                    target.relative_to(chroot_resolved)
                except ValueError:
                    raise StorageError(
                        "PATH_ESCAPE",
                        "Chroot escape attempt detected",
                        {"path": arg_str, "chroot": str(chroot)},
                        "Resolved path escapes allowed zone",
                    )

        return list(args)

    def _validate_git_command(self, args: list) -> None:
        """Validates a Git subcommand."""
        if not args:
            raise StorageError(
                "ARGUMENT_FORBIDDEN",
                "Git command without subcommand",
                {},
                "Example: git status, git log",
            )

        subcmd = args[0]

        if subcmd in GIT_BLACKLIST:
            raise StorageError(
                "COMMAND_FORBIDDEN",
                f"Command 'git {subcmd}' is forbidden",
                {"subcommand": subcmd},
                "push, pull, fetch, clone and remote are forbidden",
            )

        if subcmd not in GIT_WHITELIST_READ and subcmd not in GIT_WHITELIST_WRITE:
            raise StorageError(
                "COMMAND_FORBIDDEN",
                f"Git subcommand '{subcmd}' is not allowed",
                {
                    "subcommand": subcmd,
                    "allowed_read": sorted(GIT_WHITELIST_READ),
                    "allowed_write": sorted(GIT_WHITELIST_WRITE),
                },
            )

    def _exec_command(self, cmd: str, args: list, cwd: Path, timeout: int) -> dict:
        """Executes a command and returns the result."""
        # Build command
        full_cmd = [cmd] + [str(a) for a in args]

        try:
            result = subprocess.run(
                full_cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }

        except subprocess.TimeoutExpired:
            raise StorageError(
                "TIMEOUT",
                f"Command timeout after {timeout}s",
                {"command": cmd, "timeout": timeout},
                f"Increase timeout (max: {self.valves.exec_timeout_max}s)",
            )
        except FileNotFoundError:
            raise StorageError(
                "COMMAND_NOT_FOUND",
                f"Command '{cmd}' not found on system",
                {"command": cmd},
                "Use store_allowed_commands() to see available commands",
            )
        except Exception as e:
            raise StorageError(
                "EXEC_ERROR",
                f"Execution error: {str(e)}",
                {"command": cmd, "error": str(e)},
            )

    def _ensure_dir(self, path: Path) -> None:
        """Creates a directory and its parents if needed."""
        path.mkdir(parents=True, exist_ok=True)

    def _rm_with_empty_parents(self, filepath: Path, stop_at: Path) -> None:
        """Deletes a file then walks up deleting empty folders."""
        if filepath.exists():
            if filepath.is_dir():
                shutil.rmtree(filepath)
            else:
                filepath.unlink()

        # Walk up and delete empty folders
        parent = filepath.parent
        stop_at_resolved = stop_at.resolve()

        while parent.resolve() != stop_at_resolved:
            try:
                parent.rmdir()  # Fails if not empty
                parent = parent.parent
            except OSError:
                break

    def _get_lock_path(self, zone_root: Path, relative_path: str) -> Path:
        """Returns the lock file path."""
        return zone_root / "locks" / (relative_path + ".lock")

    def _get_editzone_path(
        self, zone_root: Path, conv_id: str, relative_path: str
    ) -> Path:
        """Returns the path in editzone."""
        return zone_root / "editzone" / conv_id / relative_path

    def _check_lock(self, lock_path: Path, conv_id: str) -> None:
        """Checks if a file is locked by another conversation."""
        if lock_path.exists():
            try:
                lock_data = json.loads(lock_path.read_text())
                if lock_data.get("conv_id") != conv_id:
                    raise StorageError(
                        "FILE_LOCKED",
                        f"File locked by conversation {lock_data.get('conv_id')}",
                        {
                            "locked_by": lock_data.get("conv_id"),
                            "locked_since": lock_data.get("locked_at"),
                            "path": lock_data.get("path"),
                        },
                        "Wait or use store_force_unlock() / store_maintenance()",
                    )
            except json.JSONDecodeError:
                pass  # Corrupted lock, will be cleaned by store_maintenance()

    def _create_lock(
        self, lock_path: Path, conv_id: str, user_id: str, path: str
    ) -> None:
        """Creates a lock file."""
        self._ensure_dir(lock_path.parent)
        lock_data = {
            "conv_id": conv_id,
            "user_id": user_id,
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "path": path,
        }
        lock_path.write_text(json.dumps(lock_data, indent=2))

    def _validate_content_size(self, content: str) -> None:
        """Checks that content doesn't exceed max size."""
        max_bytes = self.valves.max_file_size_mb * 1024 * 1024
        if len(content.encode("utf-8")) > max_bytes:
            raise StorageError(
                "QUOTA_EXCEEDED",
                f"Content too large ({len(content.encode('utf-8')) / 1024 / 1024:.2f} MB)",
                {"max_mb": self.valves.max_file_size_mb},
                f"Max size is {self.valves.max_file_size_mb} MB",
            )

    def _init_git_repo(self, repo_path: Path) -> None:
        """Initializes a Git repository if needed."""
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            self._ensure_dir(repo_path)
            subprocess.run(
                ["git", "init"],
                cwd=str(repo_path),
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "storage@openwebui.local"],
                cwd=str(repo_path),
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "User Storage"],
                cwd=str(repo_path),
                capture_output=True,
            )

    def _git_commit(self, repo_path: Path, message: str) -> None:
        """Performs a Git commit."""
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(repo_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty-message"],
            cwd=str(repo_path),
            capture_output=True,
        )

    def _format_response(
        self, success: bool, data: Any = None, message: str = None
    ) -> str:
        """Formats a JSON response."""
        response = {"success": success}
        if data is not None:
            response["data"] = data
        if message:
            response["message"] = message
        return json.dumps(response, indent=2, ensure_ascii=False)

    def _clamp_timeout(self, timeout: int) -> int:
        """Clamps timeout to configured values."""
        return max(1, min(timeout, self.valves.exec_timeout_max))

    # =========================================================================
    # UPLOADS (2 functions)
    # =========================================================================

    async def store_uploads_exec(
        self,
        cmd: str,
        args: list,
        timeout: int = 30,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Executes a command in Uploads/ (read-only).

        :param cmd: Command to execute
        :param args: Command arguments
        :param timeout: Timeout in seconds (default: 30, max: 300)
        :return: Command result as JSON
        """
        try:
            # Paths
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            chroot = user_root / "Uploads" / conv_id

            if not chroot.exists():
                return self._format_response(
                    False, message="No files uploaded in this conversation"
                )

            # Validation
            self._validate_command(cmd, WHITELIST_READONLY)
            self._validate_args(args, readonly=True)

            # Validate and resolve paths in arguments
            safe_args = self._validate_path_args(args, chroot)

            # Execution
            timeout = self._clamp_timeout(timeout)
            result = self._exec_command(cmd, safe_args, chroot, timeout)
            return self._format_response(True, result)

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_uploads_delete(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Deletes a file/folder in Uploads/.

        :param path: Relative path of file/folder to delete
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            chroot = user_root / "Uploads" / conv_id

            target = self._resolve_chroot_path(chroot, path)

            if not target.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {path}")

            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

            return self._format_response(True, message=f"Deleted: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    # =========================================================================
    # STORAGE - Normal operations (4 functions)
    # =========================================================================

    async def store_storage_exec(
        self,
        cmd: str,
        args: list,
        timeout: int = 30,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Executes a command in Storage/data/.

        :param cmd: Command to execute
        :param args: Command arguments
        :param timeout: Timeout in seconds (default: 30, max: 300)
        :return: Command result as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Storage" / "data"
            self._ensure_dir(chroot)

            # Validation
            self._validate_command(cmd, WHITELIST_READWRITE, args)
            self._validate_args(args)

            # Validate and resolve paths in arguments
            safe_args = self._validate_path_args(args, chroot)

            # Execution
            timeout = self._clamp_timeout(timeout)
            result = self._exec_command(cmd, safe_args, chroot, timeout)
            return self._format_response(True, result)

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_write(
        self,
        path: str,
        content: str,
        append: bool = False,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Writes content to Storage/data/.

        :param path: Relative file path
        :param content: Content to write
        :param append: If True, appends to end of file
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Storage" / "data"
            self._ensure_dir(chroot)

            # Validate content size
            self._validate_content_size(content)

            target = self._resolve_chroot_path(chroot, path)
            self._ensure_dir(target.parent)

            if append and target.exists():
                with target.open("a") as f:
                    f.write(content)
            else:
                target.write_text(content)

            return self._format_response(
                True, message=f"Written: {path}", data={"bytes": len(content)}
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_delete(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Deletes a file/folder in Storage/data/.

        :param path: Relative path
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Storage" / "data"

            target = self._resolve_chroot_path(chroot, path)

            if not target.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {path}")

            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

            return self._format_response(True, message=f"Deleted: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_rename(
        self,
        old_path: str,
        new_path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Renames/moves a file in Storage/data/.

        :param old_path: Current path
        :param new_path: New path
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Storage" / "data"

            source = self._resolve_chroot_path(chroot, old_path)
            dest = self._resolve_chroot_path(chroot, new_path)

            if not source.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {old_path}")

            self._ensure_dir(dest.parent)
            shutil.move(str(source), str(dest))

            return self._format_response(
                True, message=f"Renamed: {old_path} → {new_path}"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    # =========================================================================
    # STORAGE - Safe editing (5 functions)
    # =========================================================================

    async def store_storage_edit_open(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Locks a file/folder and copies it to the edit zone.

        :param path: Relative path of file/folder
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            user_id = __user__.get("id", "anonymous")
            conv_id = self._get_conv_id(__metadata__)

            # Valider le path
            path = self._validate_relative_path(path)

            zone_root = user_root / "Storage"
            data_path = zone_root / "data" / path
            lock_path = self._get_lock_path(zone_root, path)
            edit_path = self._get_editzone_path(zone_root, conv_id, path)

            # Check that source exists
            if not data_path.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {path}")

            # Check lock
            self._check_lock(lock_path, conv_id)

            # Create lock
            self._create_lock(lock_path, conv_id, user_id, path)

            # Copier vers editzone
            self._ensure_dir(edit_path.parent)
            if data_path.is_dir():
                shutil.copytree(data_path, edit_path)
            else:
                shutil.copy2(data_path, edit_path)

            return self._format_response(True, message=f"Opened for editing: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_edit_exec(
        self,
        cmd: str,
        args: list,
        timeout: int = 30,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Executes a command in the edit zone.

        :param cmd: Command to execute
        :param args: Command arguments
        :param timeout: Timeout en secondes
        :return: Command result as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            chroot = user_root / "Storage" / "editzone" / conv_id

            if not chroot.exists():
                raise StorageError(
                    "ZONE_FORBIDDEN",
                    "No file opened for editing",
                    {},
                    "Utilisez d'abord store_storage_edit_open()",
                )

            # Validation
            self._validate_command(cmd, WHITELIST_READWRITE, args)
            self._validate_args(args)

            # Validate and resolve paths in arguments
            safe_args = self._validate_path_args(args, chroot)

            # Execution
            timeout = self._clamp_timeout(timeout)
            result = self._exec_command(cmd, safe_args, chroot, timeout)
            return self._format_response(True, result)

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_edit_write(
        self,
        path: str,
        content: str,
        append: bool = False,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Writes content to the edit zone.

        :param path: Relative file path
        :param content: Content to write
        :param append: If True, appends to end
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            chroot = user_root / "Storage" / "editzone" / conv_id

            if not chroot.exists():
                raise StorageError(
                    "ZONE_FORBIDDEN",
                    "No file opened for editing",
                    {},
                    "Utilisez d'abord store_storage_edit_open()",
                )

            # Valider la taille du contenu
            self._validate_content_size(content)

            target = self._resolve_chroot_path(chroot, path)
            self._ensure_dir(target.parent)

            if append and target.exists():
                with target.open("a") as f:
                    f.write(content)
            else:
                target.write_text(content)

            return self._format_response(True, message=f"Written to editzone: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_edit_save(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Saves changes from the edit zone to data/.

        :param path: Relative path of file/folder
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)

            # Valider le path
            path = self._validate_relative_path(path)

            zone_root = user_root / "Storage"
            data_path = zone_root / "data" / path
            lock_path = self._get_lock_path(zone_root, path)
            edit_path = self._get_editzone_path(zone_root, conv_id, path)

            if not edit_path.exists():
                raise StorageError(
                    "FILE_NOT_FOUND", f"File not found in editzone: {path}"
                )

            # Copier vers data
            self._ensure_dir(data_path.parent)
            if data_path.exists():
                if data_path.is_dir():
                    shutil.rmtree(data_path)
                else:
                    data_path.unlink()

            if edit_path.is_dir():
                shutil.copytree(edit_path, data_path)
            else:
                shutil.copy2(edit_path, data_path)

            # Cleanup editzone and lock
            self._rm_with_empty_parents(edit_path, zone_root / "editzone")
            self._rm_with_empty_parents(lock_path, zone_root / "locks")

            return self._format_response(True, message=f"Saved: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_edit_cancel(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Cancels modifications (the original stays intact).

        :param path: Relative path of file/folder
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)

            # Valider le path
            path = self._validate_relative_path(path)

            zone_root = user_root / "Storage"
            lock_path = self._get_lock_path(zone_root, path)
            edit_path = self._get_editzone_path(zone_root, conv_id, path)

            # Cleanup editzone and lock
            if edit_path.exists():
                self._rm_with_empty_parents(edit_path, zone_root / "editzone")
            if lock_path.exists():
                self._rm_with_empty_parents(lock_path, zone_root / "locks")

            return self._format_response(
                True, message=f"Cancelled: {path} (original intact)"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    # =========================================================================
    # DOCUMENTS - Normal operations (4 functions)
    # =========================================================================

    async def store_documents_exec(
        self,
        cmd: str,
        args: list,
        timeout: int = 30,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Executes a command in Documents/data/ (includes Git commands).

        :param cmd: Command to execute (ou "git")
        :param args: Command arguments
        :param timeout: Timeout en secondes
        :return: Command result as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Documents" / "data"

            # Initialize Git if needed
            self._init_git_repo(chroot)

            # Validation
            self._validate_command(cmd, WHITELIST_READWRITE, args)
            self._validate_args(args)

            # Validate and resolve paths in arguments
            safe_args = self._validate_path_args(args, chroot)

            # Execution
            timeout = self._clamp_timeout(timeout)
            result = self._exec_command(cmd, safe_args, chroot, timeout)
            return self._format_response(True, result)

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_write(
        self,
        path: str,
        content: str,
        append: bool = False,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Writes content to Documents/data/ with automatic Git commit.

        :param path: Relative file path
        :param content: Content to write
        :param append: If True, appends to end
        :param message: Commit message (auto-generated if empty)
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Documents" / "data"

            # Initialiser Git
            self._init_git_repo(chroot)

            # Valider la taille du contenu
            self._validate_content_size(content)

            target = self._resolve_chroot_path(chroot, path)
            self._ensure_dir(target.parent)

            # Writing
            is_new = not target.exists()
            if append and target.exists():
                with target.open("a") as f:
                    f.write(content)
            else:
                target.write_text(content)

            # Commit
            if not message:
                action = (
                    "Created" if is_new else ("Appended to" if append else "Modified")
                )
                message = f"{action} {path}"

            self._git_commit(chroot, message)

            return self._format_response(True, message=f"Written and committed: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_delete(
        self,
        path: str,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Deletes a file/folder avec git rm + commit.

        :param path: Relative path
        :param message: Commit message
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Documents" / "data"

            target = self._resolve_chroot_path(chroot, path)

            if not target.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {path}")

            # git rm
            subprocess.run(
                ["git", "rm", "-rf", path],
                cwd=str(chroot),
                capture_output=True,
            )

            # Commit
            if not message:
                message = f"Suppression de {path}"
            self._git_commit(chroot, message)

            return self._format_response(True, message=f"Deleted and committed: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_rename(
        self,
        old_path: str,
        new_path: str,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Renames with git mv + commit.

        :param old_path: Current path
        :param new_path: New path
        :param message: Commit message
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            chroot = user_root / "Documents" / "data"

            source = self._resolve_chroot_path(chroot, old_path)
            dest = self._resolve_chroot_path(chroot, new_path)

            if not source.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {old_path}")

            self._ensure_dir(dest.parent)

            # git mv
            subprocess.run(
                ["git", "mv", old_path, new_path],
                cwd=str(chroot),
                capture_output=True,
            )

            # Commit
            if not message:
                message = f"Renommage {old_path} → {new_path}"
            self._git_commit(chroot, message)

            return self._format_response(
                True, message=f"Renamed and committed: {old_path} → {new_path}"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    # =========================================================================
    # DOCUMENTS - Safe editing (5 functions)
    # =========================================================================

    async def store_documents_edit_open(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Locks and copies a file/folder to the edit zone.

        :param path: Relative path
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            user_id = __user__.get("id", "anonymous")
            conv_id = self._get_conv_id(__metadata__)

            # Valider le path
            path = self._validate_relative_path(path)

            zone_root = user_root / "Documents"
            data_path = zone_root / "data" / path
            lock_path = self._get_lock_path(zone_root, path)
            edit_path = self._get_editzone_path(zone_root, conv_id, path)

            # Check source
            if not data_path.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {path}")

            # Check lock
            self._check_lock(lock_path, conv_id)

            # Create lock
            self._create_lock(lock_path, conv_id, user_id, path)

            # Copier vers editzone
            self._ensure_dir(edit_path.parent)
            if data_path.is_dir():
                shutil.copytree(data_path, edit_path)
            else:
                shutil.copy2(data_path, edit_path)

            return self._format_response(True, message=f"Opened for editing: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_edit_exec(
        self,
        cmd: str,
        args: list,
        timeout: int = 30,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Executes a command in the edit zone.

        :param cmd: Command to execute
        :param args: Arguments
        :param timeout: Timeout en secondes
        :return: Result as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            chroot = user_root / "Documents" / "editzone" / conv_id

            if not chroot.exists():
                raise StorageError(
                    "ZONE_FORBIDDEN",
                    "No file opened for editing",
                    {},
                    "Utilisez d'abord store_documents_edit_open()",
                )

            # Validation
            self._validate_command(cmd, WHITELIST_READWRITE, args)
            self._validate_args(args)

            # Validate and resolve paths in arguments
            safe_args = self._validate_path_args(args, chroot)

            # Execution
            timeout = self._clamp_timeout(timeout)
            result = self._exec_command(cmd, safe_args, chroot, timeout)
            return self._format_response(True, result)

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_edit_write(
        self,
        path: str,
        content: str,
        append: bool = False,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Writes to the edit zone.

        :param path: Relative path
        :param content: Contenu
        :param append: Append to end
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            chroot = user_root / "Documents" / "editzone" / conv_id

            if not chroot.exists():
                raise StorageError(
                    "ZONE_FORBIDDEN",
                    "No file opened for editing",
                    {},
                    "Utilisez d'abord store_documents_edit_open()",
                )

            # Valider la taille du contenu
            self._validate_content_size(content)

            target = self._resolve_chroot_path(chroot, path)
            self._ensure_dir(target.parent)

            if append and target.exists():
                with target.open("a") as f:
                    f.write(content)
            else:
                target.write_text(content)

            return self._format_response(True, message=f"Written to editzone: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_edit_save(
        self,
        path: str,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Sauvegarde + commit Git.

        :param path: Relative path
        :param message: Commit message
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)

            # Valider le path
            path = self._validate_relative_path(path)

            zone_root = user_root / "Documents"
            data_path = zone_root / "data" / path
            lock_path = self._get_lock_path(zone_root, path)
            edit_path = self._get_editzone_path(zone_root, conv_id, path)

            if not edit_path.exists():
                raise StorageError(
                    "FILE_NOT_FOUND", f"File not found in editzone: {path}"
                )

            # Copier vers data
            self._ensure_dir(data_path.parent)
            if data_path.exists():
                if data_path.is_dir():
                    shutil.rmtree(data_path)
                else:
                    data_path.unlink()

            if edit_path.is_dir():
                shutil.copytree(edit_path, data_path)
            else:
                shutil.copy2(edit_path, data_path)

            # Git commit
            if not message:
                message = f"Modified {path}"
            self._git_commit(zone_root / "data", message)

            # Cleanup
            self._rm_with_empty_parents(edit_path, zone_root / "editzone")
            self._rm_with_empty_parents(lock_path, zone_root / "locks")

            return self._format_response(True, message=f"Saved and committed: {path}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_edit_cancel(
        self,
        path: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Cancels modifications (original intact).

        :param path: Relative path
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)

            # Valider le path
            path = self._validate_relative_path(path)

            zone_root = user_root / "Documents"
            lock_path = self._get_lock_path(zone_root, path)
            edit_path = self._get_editzone_path(zone_root, conv_id, path)

            # Cleanup
            if edit_path.exists():
                self._rm_with_empty_parents(edit_path, zone_root / "editzone")
            if lock_path.exists():
                self._rm_with_empty_parents(lock_path, zone_root / "locks")

            return self._format_response(
                True, message=f"Cancelled: {path} (original intact)"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    # =========================================================================
    # BRIDGES (4 functions)
    # =========================================================================

    async def store_uploads_to_storage(
        self,
        src: str,
        dest: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Copies from Uploads/ to Storage/data/.
        IMPORTANT: Call store_import() first to import uploaded files!

        :param src: Source path in Uploads
        :param dest: Destination path in Storage
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)

            src_chroot = user_root / "Uploads" / conv_id
            dest_chroot = user_root / "Storage" / "data"

            source = self._resolve_chroot_path(src_chroot, src)
            target = self._resolve_chroot_path(dest_chroot, dest)

            if not source.exists():
                raise StorageError(
                    "FILE_NOT_FOUND",
                    f"File not found: {src}",
                    {"path": src, "uploads_dir": str(src_chroot)},
                    "Did you call store_import(import_all=True) first? Files must be imported before copying.",
                )

            self._ensure_dir(dest_chroot)
            self._ensure_dir(target.parent)

            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

            return self._format_response(
                True, message=f"Copied: Uploads/{src} → Storage/{dest}"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_uploads_to_documents(
        self,
        src: str,
        dest: str,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Copies from Uploads/ to Documents/data/ with Git commit.
        IMPORTANT: Call store_import() first to import uploaded files!

        :param src: Source path in Uploads
        :param dest: Destination path in Documents
        :param message: Commit message
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)

            src_chroot = user_root / "Uploads" / conv_id
            dest_chroot = user_root / "Documents" / "data"

            source = self._resolve_chroot_path(src_chroot, src)
            target = self._resolve_chroot_path(dest_chroot, dest)

            if not source.exists():
                raise StorageError(
                    "FILE_NOT_FOUND",
                    f"File not found: {src}",
                    {"path": src, "uploads_dir": str(src_chroot)},
                    "Did you call store_import(import_all=True) first? Files must be imported before copying.",
                )

            # Init Git
            self._init_git_repo(dest_chroot)

            self._ensure_dir(target.parent)

            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

            # Commit
            if not message:
                message = f"Import {src}"
            self._git_commit(dest_chroot, message)

            return self._format_response(
                True, message=f"Copied and committed: Uploads/{src} → Documents/{dest}"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_storage_to_documents(
        self,
        src: str,
        dest: str,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Copie depuis Storage vers Documents avec commit Git.

        :param src: Source path
        :param dest: Destination path
        :param message: Commit message
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)

            src_chroot = user_root / "Storage" / "data"
            dest_chroot = user_root / "Documents" / "data"

            source = self._resolve_chroot_path(src_chroot, src)
            target = self._resolve_chroot_path(dest_chroot, dest)

            if not source.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {src}")

            # Init Git
            self._init_git_repo(dest_chroot)

            self._ensure_dir(target.parent)

            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

            # Commit
            if not message:
                message = f"Import depuis Storage: {src}"
            self._git_commit(dest_chroot, message)

            return self._format_response(
                True, message=f"Copied and committed: Storage/{src} → Documents/{dest}"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_documents_to_storage(
        self,
        src: str,
        dest: str,
        message: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Moves from Documents to Storage with git rm + commit.

        :param src: Source path
        :param dest: Destination path
        :param message: Commit message
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)

            src_chroot = user_root / "Documents" / "data"
            dest_chroot = user_root / "Storage" / "data"

            source = self._resolve_chroot_path(src_chroot, src)
            target = self._resolve_chroot_path(dest_chroot, dest)

            if not source.exists():
                raise StorageError("FILE_NOT_FOUND", f"File not found: {src}")

            self._ensure_dir(dest_chroot)
            self._ensure_dir(target.parent)

            # Copier vers Storage
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

            # git rm in Documents
            subprocess.run(
                ["git", "rm", "-rf", src],
                cwd=str(src_chroot),
                capture_output=True,
            )

            # Commit
            if not message:
                message = f"Move to Storage: {src}"
            self._git_commit(src_chroot, message)

            return self._format_response(
                True, message=f"Moved: Documents/{src} → Storage/{dest}"
            )

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    # =========================================================================
    # UTILITIES (5 functions)
    # =========================================================================

    async def store_import(
        self,
        filename: str = "",
        import_all: bool = False,
        dest_subdir: str = "",
        __user__: dict = {},
        __metadata__: dict = {},
        __files__: list = None,
        __event_emitter__=None,
    ) -> str:
        """
        STEP 1: Imports files from chat to Uploads/.

        ALWAYS call this function first when user uploads a file!

        :param filename: Specific file name to import (optional)
        :param import_all: True to import ALL files (recommended)
        :param dest_subdir: Sous-dossier de destination (optionnel)
        :return: List of imported files

        Exemple: store_import(import_all=True)
        """
        try:
            user_root = self._get_user_root(__user__)
            conv_id = self._get_conv_id(__metadata__)
            uploads_dir = user_root / "Uploads" / conv_id

            if dest_subdir:
                # Valider dest_subdir
                dest_subdir = self._validate_relative_path(dest_subdir)
                if dest_subdir:
                    uploads_dir = uploads_dir / dest_subdir

            self._ensure_dir(uploads_dir)

            # Get files (try multiple sources)
            files = __files__ or []

            if not files:
                files = __metadata__.get("files", [])

            if not files:
                return self._format_response(
                    False, message="No files attached to conversation"
                )

            imported = []
            errors = []

            # Possible paths for Open WebUI files
            owui_upload_paths = [
                Path("/app/backend/data/uploads"),
                Path("/app/backend/data/files"),
                Path("/app/backend/data/cache/files"),
                Path("/app/backend/data/cache/uploads"),
            ]

            for file_info in files:
                try:
                    file_path = None
                    file_name = None
                    file_id = None
                    user_id_from_file = None

                    if isinstance(file_info, dict):
                        # Open WebUI structure detected
                        file_name = file_info.get("name") or file_info.get("filename")
                        file_id = file_info.get("id")

                        # Search in nested "file" dict
                        nested_file = file_info.get("file")
                        if isinstance(nested_file, dict):
                            file_path = nested_file.get("path") or nested_file.get(
                                "file_path"
                            )
                            user_id_from_file = nested_file.get("user_id")
                            if not file_name:
                                file_name = nested_file.get(
                                    "filename"
                                ) or nested_file.get("name")
                            if not file_id:
                                file_id = nested_file.get("id")

                        # Try direct keys if not found
                        if not file_path:
                            file_path = file_info.get("path") or file_info.get(
                                "file_path"
                            )

                        # If no direct path, search file by ID
                        if not file_path and file_id:
                            # Search in different possible paths
                            for base_path in owui_upload_paths:
                                if not base_path.exists():
                                    continue

                                # Format Open WebUI: {id}_{name}
                                if file_name:
                                    candidate = base_path / f"{file_id}_{file_name}"
                                    if candidate.exists():
                                        file_path = str(candidate)
                                        break

                                # Essayer: /base/file_id
                                candidate = base_path / file_id
                                if candidate.exists():
                                    file_path = str(candidate)
                                    break

                                # Essayer: /base/user_id/file_id
                                if user_id_from_file:
                                    candidate = base_path / user_id_from_file / file_id
                                    if candidate.exists():
                                        file_path = str(candidate)
                                        break

                                # Chercher par pattern {id}_*
                                for f in base_path.glob(f"{file_id}_*"):
                                    file_path = str(f)
                                    if not file_name:
                                        file_name = (
                                            f.name.split("_", 1)[1]
                                            if "_" in f.name
                                            else f.name
                                        )
                                    break
                                if file_path:
                                    break

                    elif isinstance(file_info, str):
                        file_path = file_info
                        file_name = Path(file_info).name

                    if not file_name:
                        file_name = file_id or "unknown"

                    # Security: clean filename (prevent traversal)
                    file_name = Path(
                        file_name
                    ).name  # Garde seulement le nom, pas le chemin
                    if not file_name or file_name in (".", ".."):
                        file_name = file_id or "unknown"

                    # Filter if filename specified
                    if filename and file_name != filename:
                        continue

                    if not import_all and not filename:
                        continue

                    # Copy the file
                    if file_path and isinstance(file_path, str):
                        source = Path(file_path)
                        if source.exists():
                            dest = uploads_dir / file_name
                            shutil.copy2(source, dest)
                            imported.append(file_name)
                        else:
                            errors.append(f"{file_name}: file not found ({file_path})")
                    else:
                        errors.append(f"{file_name}: source file not found")

                except Exception as e:
                    errors.append(f"Erreur: {str(e)}")

            if not imported:
                return self._format_response(
                    False,
                    message="No matching files found",
                    data={"errors": errors} if errors else None,
                )

            result_data = {"imported": imported, "count": len(imported)}
            if errors:
                result_data["errors"] = errors

            return self._format_response(
                True, data=result_data, message=f"Imported {len(imported)} file(s)"
            )

        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_help(
        self,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Displays complete documentation.

        :return: Documentation as text
        """
        help_text = """
# User Storage v2.4.1 - Documentation

## IMPORTANT: FILE UPLOAD WORKFLOW
When a file is uploaded, you MUST follow these steps:
  STEP 1: store_import(import_all=True)  <- ALWAYS FIRST!
  STEP 2: store_uploads_to_storage(src="filename", dest="filename")
NEVER skip step 1!

## ZONES (isolated areas)
- **Uploads/**   : Files imported from chat (read + delete only)
- **Storage/**   : User free space (all operations, git if repo present)
- **Documents/** : Git versioned space (auto-initialized repo)

## MAIN FUNCTIONS

### Uploads (read-only)
- store_import(import_all=True)
- store_uploads_exec(cmd, args)
- store_uploads_delete(path)

### Storage (all operations)
- store_storage_exec(cmd, args)
- store_storage_write(path, content, append=False)
- store_storage_delete(path)
- store_storage_rename(old_path, new_path)

### Storage - Safe editing (rollback possible)
- store_storage_edit_open(path)
- store_storage_edit_exec(cmd, args)
- store_storage_edit_write(path, content)
- store_storage_edit_save(path)
- store_storage_edit_cancel(path)

### Documents (Git versioned)
- store_documents_exec(cmd, args)
- store_documents_write(path, content, message)
- store_documents_delete(path, message)
- store_documents_rename(old_path, new_path, message)

### Documents - Safe editing
- store_documents_edit_open(path)
- store_documents_edit_exec(cmd, args)
- store_documents_edit_write(path, content)
- store_documents_edit_save(path, message)
- store_documents_edit_cancel(path)

### Bridges
- store_uploads_to_storage(src, dest)
- store_uploads_to_documents(src, dest, message)
- store_storage_to_documents(src, dest, message)
- store_documents_to_storage(src, dest, message)

### Utilities
- store_help()
- store_stats()
- store_allowed_commands()
- store_force_unlock(path, zone)
- store_maintenance()

## ALLOWED COMMANDS
Use store_allowed_commands() to see available commands.

## FORBIDDEN ARGUMENTS
; | && & > >> $( ` are forbidden in arguments.
"""
        return help_text

    async def store_stats(
        self,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Returns usage statistics.

        :return: Statistiques en JSON
        """
        try:
            user_root = self._get_user_root(__user__)

            def get_dir_size(path: Path) -> int:
                if not path.exists():
                    return 0
                total = 0
                for f in path.rglob("*"):
                    if f.is_file():
                        total += f.stat().st_size
                return total

            def count_files(path: Path) -> int:
                if not path.exists():
                    return 0
                return sum(1 for f in path.rglob("*") if f.is_file())

            uploads_size = get_dir_size(user_root / "Uploads")
            storage_size = get_dir_size(user_root / "Storage" / "data")
            documents_size = get_dir_size(user_root / "Documents" / "data")

            total_size = uploads_size + storage_size + documents_size
            quota = self.valves.quota_per_user_mb * 1024 * 1024

            stats = {
                "uploads": {
                    "size_bytes": uploads_size,
                    "size_human": f"{uploads_size / 1024 / 1024:.2f} MB",
                    "files": count_files(user_root / "Uploads"),
                },
                "storage": {
                    "size_bytes": storage_size,
                    "size_human": f"{storage_size / 1024 / 1024:.2f} MB",
                    "files": count_files(user_root / "Storage" / "data"),
                },
                "documents": {
                    "size_bytes": documents_size,
                    "size_human": f"{documents_size / 1024 / 1024:.2f} MB",
                    "files": count_files(user_root / "Documents" / "data"),
                },
                "total": {
                    "size_bytes": total_size,
                    "size_human": f"{total_size / 1024 / 1024:.2f} MB",
                    "quota_mb": self.valves.quota_per_user_mb,
                    "usage_percent": f"{(total_size / quota) * 100:.1f}%",
                },
            }

            return self._format_response(True, data=stats)

        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_allowed_commands(
        self,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Tests available commands in container.

        :return: Liste des commandes disponibles/manquantes par zone
        """
        try:
            # Cache the result
            if self._commands_cache is not None:
                return self._format_response(True, data=self._commands_cache)

            def check_command(cmd: str) -> bool:
                try:
                    result = subprocess.run(
                        ["which", cmd],
                        capture_output=True,
                        timeout=5,
                    )
                    return result.returncode == 0
                except:
                    return False

            # Check all commands
            all_commands = WHITELIST_READWRITE
            available = []
            missing = []

            for cmd in sorted(all_commands):
                if check_command(cmd):
                    available.append(cmd)
                else:
                    missing.append(cmd)

            result = {
                "uploads": {
                    "available": [c for c in available if c in WHITELIST_READONLY],
                    "missing": [c for c in missing if c in WHITELIST_READONLY],
                },
                "storage": {
                    "available": [c for c in available if c in WHITELIST_READWRITE],
                    "missing": [c for c in missing if c in WHITELIST_READWRITE],
                },
                "documents": {
                    "available": [c for c in available if c in WHITELIST_READWRITE],
                    "missing": [c for c in missing if c in WHITELIST_READWRITE],
                },
                "summary": {
                    "total_whitelist": len(all_commands),
                    "available": len(available),
                    "missing": len(missing),
                    "coverage": f"{(len(available) / len(all_commands)) * 100:.1f}%",
                },
            }

            self._commands_cache = result
            return self._format_response(True, data=result)

        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_force_unlock(
        self,
        path: str,
        zone: str,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Forces file unlock (crash recovery).

        :param path: File path
        :param zone: "storage" ou "documents"
        :return: Confirmation as JSON
        """
        try:
            user_root = self._get_user_root(__user__)

            # Valider le path
            path = self._validate_relative_path(path)

            if zone.lower() not in ("storage", "documents"):
                raise StorageError(
                    "ZONE_FORBIDDEN",
                    f"Zone invalide: {zone}",
                    {},
                    "Utilisez 'storage' ou 'documents'",
                )

            zone_name = "Storage" if zone.lower() == "storage" else "Documents"
            zone_root = user_root / zone_name

            lock_path = self._get_lock_path(zone_root, path)

            # Trouver et supprimer toutes les editzones pour ce path
            editzone_base = zone_root / "editzone"
            if editzone_base.exists():
                for conv_dir in editzone_base.iterdir():
                    if conv_dir.is_dir():
                        edit_path = conv_dir / path
                        if edit_path.exists():
                            self._rm_with_empty_parents(edit_path, editzone_base)

            # Supprimer le lock
            if lock_path.exists():
                self._rm_with_empty_parents(lock_path, zone_root / "locks")

            return self._format_response(True, message=f"Unlocked: {path} in {zone}")

        except StorageError as e:
            return json.dumps(e.to_dict(), indent=2)
        except Exception as e:
            return self._format_response(False, message=str(e))

    async def store_maintenance(
        self,
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> str:
        """
        Cleans expired locks and orphan editzones.

        :return: Rapport de nettoyage en JSON
        """
        try:
            user_root = self._get_user_root(__user__)
            max_age_hours = self.valves.lock_max_age_hours
            now = datetime.now(timezone.utc)

            cleaned = {
                "expired_locks": [],
                "corrupted_locks": [],
                "orphan_editzones": [],
            }

            for zone_name in ("Storage", "Documents"):
                zone_root = user_root / zone_name
                locks_dir = zone_root / "locks"
                editzone_dir = zone_root / "editzone"

                # 1. Clean expired and corrupted locks
                if locks_dir.exists():
                    for lock_file in locks_dir.rglob("*.lock"):
                        try:
                            lock_data = json.loads(lock_file.read_text())
                            locked_at_str = lock_data.get("locked_at", "")

                            if locked_at_str:
                                locked_at = datetime.fromisoformat(
                                    locked_at_str.replace("Z", "+00:00")
                                )
                                age_hours = (now - locked_at).total_seconds() / 3600

                                if age_hours > max_age_hours:
                                    # Expired lock
                                    rel_path = lock_file.relative_to(locks_dir)
                                    path_str = str(rel_path)[:-5]  # Enlever .lock

                                    # Delete associated editzone
                                    conv_id = lock_data.get("conv_id", "")
                                    if conv_id:
                                        edit_path = editzone_dir / conv_id / path_str
                                        if edit_path.exists():
                                            self._rm_with_empty_parents(
                                                edit_path, editzone_dir
                                            )

                                    # Supprimer le lock
                                    self._rm_with_empty_parents(lock_file, locks_dir)
                                    cleaned["expired_locks"].append(
                                        f"{zone_name}/{path_str}"
                                    )

                        except json.JSONDecodeError:
                            # Lock corrompu
                            rel_path = lock_file.relative_to(locks_dir)
                            self._rm_with_empty_parents(lock_file, locks_dir)
                            cleaned["corrupted_locks"].append(f"{zone_name}/{rel_path}")
                        except (ValueError, TypeError):
                            pass  # Date invalide, ignorer

                # 2. Clean orphan editzones (without corresponding lock)
                if editzone_dir.exists():
                    for conv_dir in editzone_dir.iterdir():
                        if conv_dir.is_dir():
                            for item in conv_dir.rglob("*"):
                                if item.is_file():
                                    # Trouver le chemin relatif
                                    rel_path = item.relative_to(conv_dir)
                                    lock_path = locks_dir / (str(rel_path) + ".lock")

                                    if not lock_path.exists():
                                        # Editzone orpheline
                                        self._rm_with_empty_parents(item, editzone_dir)
                                        cleaned["orphan_editzones"].append(
                                            f"{zone_name}/editzone/{conv_dir.name}/{rel_path}"
                                        )

            total = (
                len(cleaned["expired_locks"])
                + len(cleaned["corrupted_locks"])
                + len(cleaned["orphan_editzones"])
            )

            return self._format_response(
                True,
                data=cleaned,
                message=f"Maintenance complete: {total} element(s) cleaned",
            )

        except Exception as e:
            return self._format_response(False, message=str(e))