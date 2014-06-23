# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""Functional tests for the ``flocker-volume`` command line tool."""

from subprocess import check_output, Popen, PIPE
import json
import os
from unittest import skipIf, skipUnless

from twisted.trial.unittest import TestCase
from twisted.python.filepath import FilePath
from twisted.internet import reactor

from ... import __version__
from ..service import VolumeService, Volume
from .._ipc import ProcessNode
from ..filesystems.zfs import StoragePool
from .test_filesystems_zfs import create_zfs_pool


_require_installed = skipUnless(os.getenv("FLOCKER_INSTALLED"),
                                "flocker-volume not installed")


def run(*args):
    """Run ``flocker-volume`` with the given arguments.

    :param args: Additional command line arguments as ``bytes``.

    :return: The output of standard out.
    :raises: If exit code is not 0.
    """
    return check_output([b"flocker-volume"] + list(args))


def run_expecting_error(*args):
    """Run ``flocker-volume`` with the given arguments.

    :param args: Additional command line arguments as ``bytes``.

    :return: The output of standard error.
    :raises: If exit code is 0.
    """
    process = Popen([b"flocker-volume"] + list(args), stderr=PIPE)
    result = process.stderr.read()
    exit_code = process.wait()
    if exit_code == 0:
        raise AssertionError("flocker-volume exited with code 0.")
    return result


class FlockerVolumeTests(TestCase):
    """Tests for ``flocker-volume``."""

    @_require_installed
    def setUp(self):
        pass

    def test_version(self):
        """``flocker-volume --version`` returns the current version."""
        result = run(b"--version")
        self.assertEqual(result, b"%s\n" % (__version__,))

    def test_config(self):
        """``flocker-volume --config path`` writes a JSON file at that path."""
        path = FilePath(self.mktemp())
        run(b"--config", path.path)
        self.assertTrue(json.loads(path.getContent()))

    @skipIf(os.getuid() == 0, "root doesn't get permission errors.")
    def test_no_permission(self):
        """If the config file is not writeable a meaningful response is
        written.
        """
        path = FilePath(self.mktemp())
        path.makedirs()
        path.chmod(0)
        self.addCleanup(path.chmod, 0o777)
        config = path.child(b"out.json")
        result = run_expecting_error(b"--config", config.path)
        self.assertEqual(result,
                         b"Writing config file %s failed: Permission denied\n"
                         % (config.path,))


class ReceiveTests(TestCase):
    """Tests for ``flocker-volume receive``."""

    @_require_installed
    def setUp(self):
        self.from_pool = StoragePool(reactor, create_zfs_pool(self),
                                     FilePath(self.mktemp()))
        self.from_service = VolumeService(FilePath(self.mktemp()),
                                          self.from_pool)
        self.from_service.startService()

        self.to_pool = StoragePool(reactor, create_zfs_pool(self),
                                   FilePath(self.mktemp()))
        self.to_config = FilePath(self.mktemp())
        self.to_service = VolumeService(self.to_config, self.to_pool)
        self.to_service.startService()

    def test_creates_volume(self):
        """``flocker-volume receive`` creates a volume."""
        created = self.from_service.create(u"thevolume")

        def do_push(volume):
            # Blocking call:
            run_locally = ProcessNode(initial_command_arguments=[])
            self.from_service.push(volume, run_locally, self.to_config)
        created.addCallback(do_push)

        def pushed(_):
            to_volume = Volume(uuid=self.to_service.uuid, name=u"thevolume",
                               _pool=self.to_pool)
            self.assertTrue(to_volume.get_filesystem().get_path().exists())
        created.addCallback(pushed)

        return created

    def test_creates_files(self):
        """``flocker-volume receive`` recreates files pushed from origin."""
        created = self.from_service.create(u"thevolume")

        def do_push(volume):
            root = volume.get_filesystem().get_path()
            root.child(b"afile.txt").setContent(b"WORKS!")

            # Blocking call:
            run_locally = ProcessNode(initial_command_arguments=[])
            self.from_service.push(volume, run_locally, self.to_config)
        created.addCallback(do_push)

        def pushed(_):
            to_volume = Volume(uuid=self.to_service.uuid, name=u"thevolume",
                               _pool=self.to_pool)
            root = to_volume.get_filesystem().get_path()
            self.assertEqual(root.child(b"afile.txt"), b"WORKS!")
        created.addCallback(pushed)

        return created
