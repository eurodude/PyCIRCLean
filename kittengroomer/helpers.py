#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Contains the base objects for use when creating a sanitizer using
PyCIRCLean. Subclass FileBase and KittenGroomerBase to implement your
desired behavior.
"""


import os
import sys
import hashlib
import shutil
import argparse

import magic
from twiggy import quick_setup, log


class KittenGroomerError(Exception):
    """Base KittenGroomer exception handler."""

    def __init__(self, message):
        super(KittenGroomerError, self).__init__(message)
        self.message = message


class ImplementationRequired(KittenGroomerError):
    """Implementation required error."""

    pass


class FileBase(object):
    """
    Base object for individual files in the source directory. Contains file
    attributes and various helper methods. Subclass and add attributes
    or methods relevant to a given implementation.
    """

    def __init__(self, src_path, dst_path):
        """Initialized with the source path and expected destination path."""
        self.src_path = src_path
        self.dst_path = dst_path
        self.log_details = {'filepath': self.src_path}
        self.log_string = ''
        self._determine_extension()
        self._determine_mimetype()

    def _determine_extension(self):
        _, ext = os.path.splitext(self.src_path)
        self.extension = ext.lower()

    def _determine_mimetype(self):
        if os.path.islink(self.src_path):
            # magic will throw an IOError on a broken symlink
            self.mimetype = 'inode/symlink'
        else:
            try:
                mt = magic.from_file(self.src_path, mime=True)
                # magic will always return something, even if it's just 'data'
            except UnicodeEncodeError as e:
                # FIXME: The encoding of the file is broken (possibly UTF-16)
                mt = ''
                self.log_details.update({'UnicodeError': e})
            try:
                self.mimetype = mt.decode("utf-8")
            except:
                self.mimetype = mt
        if self.mimetype and '/' in self.mimetype:
            self.main_type, self.sub_type = self.mimetype.split('/')
        else:
            self.main_type = ''
            self.sub_type = ''

    def has_mimetype(self):
        """
        Returns True if file has a full mimetype, else False.

        Returns False + updates log if self.main_type or self.sub_type
        are not set.
        """
        if not self.main_type or not self.sub_type:
            self.log_details.update({'broken_mime': True})
            return False
        return True

    def has_extension(self):
        """
        Returns True if self.extension is set, else False.

        Returns False + updates self.log_details if self.extension is not set.
        """
        if self.extension == '':
            self.log_details.update({'no_extension': True})
            return False
        return True

    def is_dangerous(self):
        """Returns True if self.log_details contains 'dangerous'."""
        return ('dangerous' in self.log_details)

    def is_unknown(self):
        """Returns True if self.log_details contains 'unknown'."""
        return ('unknown' in self.log_details)

    def is_binary(self):
        """returns True if self.log_details contains 'binary'."""
        return ('binary' in self.log_details)

    def is_symlink(self):
        """Returns True and updates log if file is a symlink."""
        if self.has_mimetype() and self.main_type == 'inode' and self.sub_type == 'symlink':
            self.log_details.update({'symlink': os.readlink(self.src_path)})
            return True
        return False

    def add_log_details(self, key, value):
        """Takes a key + a value and adds them to self.log_details."""
        self.log_details[key] = value

    def make_dangerous(self):
        """
        Marks a file as dangerous.

        Prepends and appends DANGEROUS to the destination file name
        to help prevent double-click of death.
        """
        if self.is_dangerous():
            return
        self.log_details['dangerous'] = True
        path, filename = os.path.split(self.dst_path)
        self.dst_path = os.path.join(path, 'DANGEROUS_{}_DANGEROUS'.format(filename))

    def make_unknown(self):
        """Marks a file as an unknown type and prepends UNKNOWN to filename."""
        if self.is_dangerous() or self.is_binary():
            return
        self.log_details['unknown'] = True
        path, filename = os.path.split(self.dst_path)
        self.dst_path = os.path.join(path, 'UNKNOWN_{}'.format(filename))

    def make_binary(self):
        """Marks a file as a binary and appends .bin to filename."""
        if self.is_dangerous():
            return
        self.log_details['binary'] = True
        path, filename = os.path.split(self.dst_path)
        self.dst_path = os.path.join(path, '{}.bin'.format(filename))

    def force_ext(self, ext):
        """If dst_path does not end in ext, appends the ext and updates log."""
        if not self.dst_path.endswith(ext):
            self.log_details['force_ext'] = True
            self.dst_path += ext


class KittenGroomerBase(object):
    """Base object responsible for copy/sanitization process."""

    def __init__(self, root_src, root_dst, debug=False):
        """Initialized with path to source and dest directories."""
        self.src_root_dir = root_src
        self.dst_root_dir = root_dst
        self.log_root_dir = os.path.join(self.dst_root_dir, 'logs')
        self._safe_rmtree(self.log_root_dir)
        self._safe_mkdir(self.log_root_dir)
        self.log_processing = os.path.join(self.log_root_dir, 'processing.log')
        self.log_content = os.path.join(self.log_root_dir, 'content.log')
        self.tree(self.src_root_dir)

        quick_setup(file=self.log_processing)
        self.log_name = log.name('files')
        self.resources_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data')
        os.environ["PATH"] += os.pathsep + self.resources_path

        self.cur_file = None

        self.debug = debug
        if self.debug:
            self.log_debug_err = os.path.join(self.log_root_dir, 'debug_stderr.log')
            self.log_debug_out = os.path.join(self.log_root_dir, 'debug_stdout.log')
        else:
            self.log_debug_err = os.devnull
            self.log_debug_out = os.devnull

    def _computehash(self, path):
        """Returns a sha1 hash of a file at a given path."""
        s = hashlib.sha1()
        with open(path, 'rb') as f:
            while True:
                buf = f.read(0x100000)
                if not buf:
                    break
                s.update(buf)
        return s.hexdigest()

    def tree(self, base_dir, padding='   '):
        """Writes a graphical tree to the log for a given directory."""
        if sys.version_info.major == 2:
            self.__tree_py2(base_dir, padding)
        else:
            self.__tree_py3(base_dir, padding)

    def __tree_py2(self, base_dir, padding='   '):
        with open(self.log_content, 'ab') as lf:
            lf.write('#' * 80 + '\n')
            lf.write('{}+- {}/\n'.format(padding, os.path.basename(os.path.abspath(base_dir))))
            padding += '|  '
            files = sorted(os.listdir(base_dir))
            for f in files:
                curpath = os.path.join(base_dir, f)
                if os.path.islink(curpath):
                    lf.write('{}+-- {}\t- Symbolic link to {}\n'.format(padding, f, os.readlink(curpath)))
                elif os.path.isdir(curpath):
                    self.tree(curpath, padding)
                elif os.path.isfile(curpath):
                    lf.write('{}+-- {}\t- {}\n'.format(padding, f, self._computehash(curpath)))

    def __tree_py3(self, base_dir, padding='   '):
        with open(self.log_content, 'ab') as lf:
            lf.write(bytes('#' * 80 + '\n', 'UTF-8'))
            lf.write(bytes('{}+- {}/\n'.format(padding, os.path.basename(os.path.abspath(base_dir)).encode()), 'utf8'))
            padding += '|  '
            files = sorted(os.listdir(base_dir))
            for f in files:
                curpath = os.path.join(base_dir, f)
                if os.path.islink(curpath):
                    lf.write('{}+-- {}\t- Symbolic link to {}\n'.format(padding, f, os.readlink(curpath)).encode(errors='ignore'))
                elif os.path.isdir(curpath):
                    self.tree(curpath, padding)
                elif os.path.isfile(curpath):
                    lf.write('{}+-- {}\t- {}\n'.format(padding, f, self._computehash(curpath)).encode(errors='ignore'))

    # ##### Helpers #####
    def _safe_rmtree(self, directory):
        """Remove a directory tree if it exists."""
        if os.path.exists(directory):
            shutil.rmtree(directory)

    def _safe_remove(self, filepath):
        """Remove a file if it exists."""
        if os.path.exists(filepath):
            os.remove(filepath)

    def _safe_mkdir(self, directory):
        """Make a directory if it does not exist."""
        if not os.path.exists(directory):
            os.makedirs(directory)

    def _safe_copy(self, src=None, dst=None):
        """Copy a file and create directory if needed."""
        if src is None:
            src = self.cur_file.src_path
        if dst is None:
            dst = self.cur_file.dst_path
        try:
            dst_path, filename = os.path.split(dst)
            self._safe_mkdir(dst_path)
            shutil.copy(src, dst)
            return True
        except Exception as e:
            # TODO: Logfile
            print(e)
            return False

    def _safe_metadata_split(self, ext):
        """Create a separate file to hold this file's metadata."""
        # TODO: fix logic in this method
        dst = self.cur_file.dst_path
        try:
            if os.path.exists(self.cur_file.src_path + ext):  # should we check dst_path as well?
                raise KittenGroomerError("Cannot create split metadata file for \"" +
                                         self.cur_file.dst_path + "\", type '" +
                                         ext + "': File exists.")
            dst_path, filename = os.path.split(dst)
            self._safe_mkdir(dst_path)
            return open(dst + ext, 'w+')
        except Exception as e:
            # TODO: Logfile
            print(e)
            return False

    def _list_all_files(self, directory):
        """Generate an iterator over all the files in a directory tree."""
        for root, dirs, files in os.walk(directory):
            for filename in files:
                filepath = os.path.join(root, filename)
                yield filepath

    def _print_log(self):
        """
        Print log, should be called after each file.

        You probably want to reimplement it in the subclass.
        """
        tmp_log = self.log_name.fields(**self.cur_file.log_details)
        tmp_log.info('It did a thing.')

    #######################

    def processdir(self, src_dir=None, dst_dir=None):
        """
        Implement this function in your subclass to define file processing behavior.
        """
        raise ImplementationRequired('Please implement processdir.')


def main(kg_implementation, description='Call a KittenGroomer implementation to process files present in the source directory and copy them to the destination directory.'):
    parser = argparse.ArgumentParser(prog='KittenGroomer', description=description)
    parser.add_argument('-s', '--source', type=str, help='Source directory')
    parser.add_argument('-d', '--destination', type=str, help='Destination directory')
    args = parser.parse_args()
    kg = kg_implementation(args.source, args.destination)
    kg.processdir()
