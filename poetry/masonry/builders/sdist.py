import os
import tarfile

from collections import defaultdict
from copy import copy
from gzip import GzipFile
from io import BytesIO
from pathlib import Path
from posixpath import join as pjoin
from pprint import pformat
from typing import List

from poetry.packages import Dependency

from ..utils.helpers import normalize_file_permissions

from .builder import Builder


SETUP = """\
# -*- coding: utf-8 -*-
from distutils.core import setup

{before}
setup_kwargs = {{
    'name': {name!r},
    'version': {version!r},
    'description': {description!r},
    'long_description': {long_description!r},
    'author': {author!r},
    'author_email': {author_email!r},
    'url': {url!r},
    {extra}
}}
{after}

setup(**setup_kwargs)
"""


PKG_INFO = """\
Metadata-Version: 1.1
Name: {name}
Version: {version}
Summary: {summary}
Home-page: {home_page}
Author: {author}
Author-email: {author_email}
"""


class SdistBuilder(Builder):

    def build(self, target_dir: Path = None) -> Path:
        self._io.writeln(' - Building <info>sdist</info>')
        if target_dir is None:
            target_dir = self._path / 'dist'

        if not target_dir.exists():
            target_dir.mkdir(parents=True)

        target = target_dir / f'{self._package.pretty_name}' \
                              f'-{self._package.version}.tar.gz'
        gz = GzipFile(target.as_posix(), mode='wb')
        tar = tarfile.TarFile(target.as_posix(), mode='w', fileobj=gz,
                              format=tarfile.PAX_FORMAT)

        try:
            tar_dir = f'{self._package.pretty_name}-{self._package.version}'

            files_to_add = self.find_files_to_add(exclude_build=False)

            for relpath in files_to_add:
                path = self._path / relpath
                tar_info = tar.gettarinfo(
                    str(path),
                    arcname=pjoin(tar_dir, relpath)
                )
                tar_info = self.clean_tarinfo(tar_info)

                if tar_info.isreg():
                    with path.open('rb') as f:
                        tar.addfile(tar_info, f)
                else:
                    tar.addfile(tar_info)  # Symlinks & ?

            setup = self.build_setup()
            tar_info = tarfile.TarInfo(pjoin(tar_dir, 'setup.py'))
            tar_info.size = len(setup)
            tar.addfile(tar_info, BytesIO(setup))

            pkg_info = PKG_INFO.format(
                name=self._meta.name,
                version=self._meta.version,
                summary=self._meta.summary,
                home_page=self._meta.home_page,
                author=self._meta.author,
                author_email=self._meta.author_email,
            ).encode('utf-8')

            tar_info = tarfile.TarInfo(pjoin(tar_dir, 'PKG-INFO'))
            tar_info.size = len(pkg_info)
            tar.addfile(tar_info, BytesIO(pkg_info))
        finally:
            tar.close()
            gz.close()

        self._io.writeln(f' - Built <fg=cyan>{target.name}</>')

        return target

    def build_setup(self) -> bytes:
        before, extra, after = [], [], []

        # If we have a build script, use it
        if self._package.build:
            after += [
                f'from {self._package.build.split(".")[0]} import *',
                'build(setup_kwargs)'
            ]

        if self._module.is_package():
            packages, package_data = self.find_packages(
                self._module.path.as_posix()
            )
            before.append("packages = \\\n{}\n".format(pformat(sorted(packages))))
            before.append("package_data = \\\n{}\n".format(pformat(package_data)))
            extra.append("'packages': packages,")
            extra.append("'package_data': package_data,")
        else:
            extra.append("'py_modules': {!r},".format(self._module.name))

        dependencies, extras = self.convert_dependencies(
            self._package,
            self._package.requires
        )
        if dependencies:
            before.append("install_requires = \\\n{}\n".format(pformat(dependencies)))
            extra.append("'install_requires': install_requires,")

        if extras:
            before.append("extras_require = \\\n{}\n".format(pformat(extras)))
            extra.append("'extras_require': extras_require,")

        entry_points = self.convert_entry_points()
        if entry_points:
            before.append("entry_points = \\\n{}\n".format(pformat(entry_points)))
            extra.append("'entry_points': entry_points,")

        if self._package.python_versions != '*':
            python_requires = self._meta.requires_python

            extra.append("'python_requires': {!r},".format(python_requires))

        return SETUP.format(
            before='\n'.join(before),
            name=self._meta.name,
            version=self._meta.version,
            description=self._meta.summary,
            long_description=self._meta.description,
            author=self._meta.author,
            author_email=self._meta.author_email,
            url=self._meta.home_page,
            extra='\n    '.join(extra),
            after='\n'.join(after)
        ).encode('utf-8')

    @classmethod
    def find_packages(cls, path: str):
        """
        Discover subpackages and data.

        It also retrieve necessary files
        """
        pkgdir = os.path.normpath(path)
        pkg_name = os.path.basename(pkgdir)
        pkg_data = defaultdict(list)
        # Undocumented distutils feature:
        # the empty string matches all package names
        pkg_data[''].append('*')
        packages = [pkg_name]
        subpkg_paths = set()

        def find_nearest_pkg(rel_path):
            parts = rel_path.split(os.sep)
            for i in reversed(range(1, len(parts))):
                ancestor = '/'.join(parts[:i])
                if ancestor in subpkg_paths:
                    pkg = '.'.join([pkg_name] + parts[:i])
                    return pkg, '/'.join(parts[i:])

            # Relative to the top-level package
            return pkg_name, rel_path

        for path, dirnames, filenames in os.walk(pkgdir, topdown=True):
            if os.path.basename(path) == '__pycache__':
                continue

            from_top_level = os.path.relpath(path, pkgdir)
            if from_top_level == '.':
                continue

            is_subpkg = '__init__.py' in filenames
            if is_subpkg:
                subpkg_paths.add(from_top_level)
                parts = from_top_level.split(os.sep)
                packages.append('.'.join([pkg_name] + parts))
            else:
                pkg, from_nearest_pkg = find_nearest_pkg(from_top_level)
                pkg_data[pkg].append(pjoin(from_nearest_pkg, '*'))

        # Sort values in pkg_data
        pkg_data = {k: sorted(v) for (k, v) in pkg_data.items()}

        return sorted(packages), pkg_data

    @classmethod
    def convert_dependencies(cls,
                             package,
                             dependencies: List[Dependency]):
        main = []
        extras = defaultdict(list)

        for dependency in dependencies:
            if dependency.is_optional():
                for extra_name, reqs in package.extras.items():
                    for req in reqs:
                        if req.name == dependency.name:
                            extras[extra_name].append(dependency.to_pep_508())
                continue

            requirement = dependency.to_pep_508()
            main.append(requirement)

        return main, dict(extras)

    @classmethod
    def clean_tarinfo(cls, tar_info):
        """
        Clean metadata from a TarInfo object to make it more reproducible.

            - Set uid & gid to 0
            - Set uname and gname to ""
            - Normalise permissions to 644 or 755
            - Set mtime if not None
        """
        ti = copy(tar_info)
        ti.uid = 0
        ti.gid = 0
        ti.uname = ''
        ti.gname = ''
        ti.mode = normalize_file_permissions(ti.mode)
        
        return ti
