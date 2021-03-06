#!/usr/bin/env python
#
# Copyright (C) 2018 Linus Jahn <lnj@kaidan.im>
# Copyright (C) 2019-2020 Hiroshi Miura <miurahr@linux.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import xml.etree.ElementTree as ElementTree
from logging import getLogger

import requests

from aqt.helper import Settings


class ArchiveListError(Exception):
    pass


class ArchiveDownloadError(Exception):
    pass


class TargetConfig:
    def __init__(self, version, target, arch, os_name):
        self.version = version
        self.target = target
        self.arch = arch
        self.os_name = os_name


class QtPackage:
    """
      Hold package information.
    """
    def __init__(self, name, archive_url, archive, package_desc, has_mirror=False):
        self.name = name
        self.url = archive_url
        self.archive = archive
        self.desc = package_desc
        self.has_mirror = has_mirror


class ListInfo:
    """
        Hold list information
    """
    def __init__(self, name, display_name, desc, virtual):
        self.name = name
        self.display_name = display_name
        self.desc = desc
        self.virtual = virtual


class PackagesList:
    """
        Hold packages list information.
    """

    BASE_URL = 'https://download.qt.io/online/qtsdkrepository/'

    def __init__(self, version, os_name, target):
        self.version = version
        self.os_name = os_name
        self.target = target
        self.base = self.BASE_URL
        self.archives = []
        self._get_archives()

    def _get_archives(self):
        qt_ver_num = self.version.replace(".", "")

        # Get packages index
        archive_path = "{0}{1}{2}/qt5_{3}/".format(self.os_name, '_x86/' if self.os_name == 'windows' else '_x64/',
                                                   self.target, qt_ver_num)
        update_xml_url = "{0}{1}Updates.xml".format(self.BASE_URL, archive_path)
        try:
            r = requests.get(update_xml_url)
        except requests.exceptions.ConnectionError as e:
            self.logger.error('Download error: %s\n' % e.args, exc_info=True)
            raise e
        else:
            self.update_xml = ElementTree.fromstring(r.text)
            for packageupdate in self.update_xml.iter("PackageUpdate"):
                name = packageupdate.find("Name").text
                if packageupdate.find("DownloadableArchives").text is not None:
                    package_desc = packageupdate.findtext("Description")
                    display_name = packageupdate.findtext("DisplayName")
                    virtual_str = packageupdate.findtext("Virtual")
                    if virtual_str is None or virtual_str == 'false':
                        virtual = False
                    else:
                        virtual = True
                    self.archives.append(ListInfo(name, display_name, package_desc, virtual))
        if len(self.archives) == 0:
            self.logger.error("Error while parsing package information!")
            exit(1)

    def get_list(self):
        return self.archives


class QtArchives:
    """Hold Qt archive packages list."""

    BASE_URL = 'https://download.qt.io/online/qtsdkrepository/'

    def __init__(self, os_name, target, version, arch, subarchives=None,
                 modules=None, mirror=None, logging=None, all_extra=False):
        self.version = version
        self.target = target
        self.arch = arch
        self.mirror = mirror
        self.os_name = os_name
        self.all_extra = all_extra
        self.arch_list = [item.get('arch') for item in Settings().qt_combinations]
        all_archives = (subarchives is None)
        if mirror is not None:
            self.has_mirror = True
            self.base = mirror + '/online/qtsdkrepository/'
        else:
            self.has_mirror = False
            self.base = self.BASE_URL
        if logging:
            self.logger = logging
        else:
            self.logger = getLogger('aqt')
        self.archives = []
        self.mod_list = []
        qt_ver_num = self.version.replace(".", "")
        self.qt_ver_base = self.version[0:1]
        if all_extra:
            self.all_extra = True
        else:
            for m in modules if modules is not None else []:
                self.mod_list.append("qt.qt{}.{}.{}.{}".format(self.qt_ver_base, qt_ver_num, m, arch))
                self.mod_list.append("qt.{}.{}.{}".format(qt_ver_num, m, arch))
        self._get_archives(qt_ver_num)
        if not all_archives:
            self.archives = list(filter(lambda a: a.name in subarchives, self.archives))

    def _get_archives(self, qt_ver_num):
        # Get packages index
        archive_path = "{0}{1}{2}/qt{3}_{4}{5}".format(self.os_name,
                                                       '_x86/' if self.os_name == 'windows' else '_x64/',
                                                       self.target, self.qt_ver_base, qt_ver_num,
                                                       '_wasm/' if self.arch == 'wasm_32' else '/')
        update_xml_url = "{0}{1}Updates.xml".format(self.base, archive_path)
        archive_url = "{0}{1}".format(self.base, archive_path)
        target_packages = []
        target_packages.append("qt.qt{}.{}.{}".format(self.qt_ver_base, qt_ver_num, self.arch))
        target_packages.append("qt.{}.{}".format(qt_ver_num, self.arch))
        target_packages.extend(self.mod_list)
        self._download_update_xml(update_xml_url)
        self._parse_update_xml(archive_url, target_packages)

    def _download_update_xml(self, update_xml_url):
        try:
            r = requests.get(update_xml_url)
        except requests.exceptions.ConnectionError as e:
            self.logger.error('Download error: %s\n' % e.args, exc_info=True)
            raise ArchiveDownloadError("Download error!")
        else:
            if r.status_code == 200:
                self.update_xml_text = r.text
            else:
                self.logger.error('Download error when access to {}\n'
                                  'Server response code: {}, reason: {}'.format(update_xml_url,
                                                                                r.status_code, r.reason))
                raise ArchiveDownloadError("Download error!")

    def _parse_update_xml(self, archive_url, target_packages):
        try:
            self.update_xml = ElementTree.fromstring(self.update_xml_text)
        except ElementTree.ParseError as perror:
            self.logger.error("Downloaded metadata is corrupted. {}".format(perror))
            raise ArchiveListError("Downloaded metadata is corrupted.")
        else:
            for packageupdate in self.update_xml.iter("PackageUpdate"):
                name = packageupdate.find("Name").text
                # Need to filter archives to download when we want all extra modules
                if self.all_extra:
                    # Check platform
                    name_last_section = name.split(".")[-1]
                    if name_last_section in self.arch_list and self.arch != name_last_section:
                        continue
                    # Check doc/examples
                    if self.arch in ['doc', 'examples']:
                        if self.arch not in name:
                            continue
                if self.all_extra or name in target_packages:
                    if packageupdate.find("DownloadableArchives").text is not None:
                        downloadable_archives = packageupdate.find("DownloadableArchives").text.split(", ")
                        full_version = packageupdate.find("Version").text
                        package_desc = packageupdate.find("Description").text
                        for archive in downloadable_archives:
                            archive_name = archive.split('-', maxsplit=1)[0]
                            package_url = archive_url + name + "/" + full_version + archive
                            self.archives.append(QtPackage(archive_name, package_url, archive, package_desc,
                                                           has_mirror=self.has_mirror))
        if len(self.archives) == 0:
            self.logger.error("Specified packages are not found while parsing XML of package information!")
            self.logger.debug(self.update_xml_text)

    def get_archives(self):
        """
          It returns an archive package list.

         :return package list
         :rtype: List[QtPackage]
         """
        return self.archives

    def get_target_config(self) -> TargetConfig:
        """Get target configuration

        :return: configured target and its version with arch
        :rtype: TargetConfig object
        """
        return TargetConfig(self.version, self.target, self.arch, self.os_name)


class SrcDocExamplesArchives(QtArchives):
    """Hold doc/src/example archive package list."""

    def __init__(self, flavor, os_name, target, version, subarchives=None,
                 modules=None, mirror=None, logging=None, all_extra=False):
        self.flavor = flavor
        self.target = target
        self.os_name = os_name
        super(SrcDocExamplesArchives, self).__init__(os_name, target, version, self.flavor, subarchives=subarchives,
                                                     modules=modules, mirror=mirror, logging=logging,
                                                     all_extra=all_extra)

    def _get_archives(self, qt_ver_num):
        archive_path = "{0}{1}{2}/qt{3}_{4}{5}".format(self.os_name,
                                                       '_x86/' if self.os_name == 'windows' else '_x64/',
                                                       self.target, self.qt_ver_base, qt_ver_num,
                                                       '_src_doc_examples/')
        archive_url = "{0}{1}".format(self.base, archive_path)
        update_xml_url = "{0}/Updates.xml".format(archive_url)
        target_packages = []
        target_packages.append("qt.qt{}.{}.{}".format(self.qt_ver_base, qt_ver_num, self.flavor))
        target_packages.extend(self.mod_list)
        self._download_update_xml(update_xml_url)
        self._parse_update_xml(archive_url, target_packages)

    def get_target_config(self) -> TargetConfig:
        """Get target configuration.

        :return tuple of three parameter, "Tools", target and arch
        """
        return TargetConfig("src_doc_examples", self.target, self.arch, self.os_name)


class ToolArchives(QtArchives):
    """Hold tool archive package list
        when installing mingw tool, argument would be
        ToolArchive(windows, desktop, 4.9.1-3, mingw)
        when installing ifw tool, argument would be
        ToolArchive(linux, desktop, 3.1.1, ifw)
    """

    def __init__(self, os_name, tool_name, version, arch, mirror=None, logging=None):
        self.tool_name = tool_name
        self.os_name = os_name
        super(ToolArchives, self).__init__(os_name, 'desktop', version, arch, mirror=mirror, logging=logging)

    def _get_archives(self, qt_ver_num):
        if self.os_name == 'windows':
            archive_url = self.base + self.os_name + '_x86/' + self.target + '/'
        else:
            archive_url = self.base + self.os_name + '_x64/' + self.target + '/'
        update_xml_url = "{0}{1}/Updates.xml".format(archive_url, self.tool_name)
        self._download_update_xml(update_xml_url)  # call super method.
        self._parse_update_xml(archive_url, [])

    def _parse_update_xml(self, archive_url, target_packages):
        try:
            self.update_xml = ElementTree.fromstring(self.update_xml_text)
        except ElementTree.ParseError as perror:
            self.logger.error("Downloaded metadata is corrupted. {}".format(perror))
            raise ArchiveListError("Downloaded metadata is corrupted.")
        else:
            for packageupdate in self.update_xml.iter("PackageUpdate"):
                name = packageupdate.find("Name").text
                _archives = packageupdate.find("DownloadableArchives").text
                if _archives is not None:
                    downloadable_archives = _archives.split(", ")
                else:
                    downloadable_archives = []
                full_version = packageupdate.find("Version").text
                if full_version != self.version:
                    continue
                # FIXME: rules
                # if "-" in full_version:
                #    split_version = full_version.split("-")
                #    named_version = split_version[0] + "-" + split_version[1]
                # else:
                #    named_version = full_version
                named_version = full_version
                package_desc = packageupdate.find("Description").text
                for archive in downloadable_archives:
                    package_url = archive_url + self.tool_name + "/" + name + "/" + named_version + archive
                    self.archives.append(QtPackage(name, package_url, archive, package_desc,
                                                   has_mirror=(self.mirror is not None)))

    def get_target_config(self) -> TargetConfig:
        """Get target configuration.

        :return tuple of three parameter, "Tools", target and arch
        """
        return TargetConfig("Tools", self.target, self.arch, self.os_name)
