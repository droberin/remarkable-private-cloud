import logging
from zipfile import ZipFile
from tempfile import mkdtemp
from os.path import join, islink
from os.path import getsize
from os import walk
from datetime import datetime


class RemarkableCloudSkeleton:
    default_upload_directory = '/reMarkable2'

    def __init__(self):
        """
        Avoid overriding initialiser!
        """
        # Default 10 MB
        self.size_limit = 10
        self._client = None
        self.configuration = None
        self.handler_name = 'default'

    def logout(self):
        raise NotImplemented("method 'logout' must be implemented in a Cloud Provider Handler")

    def login(self):
        raise NotImplemented("method 'login' must be implemented in a Cloud Provider Handler")

    @property
    def handler_name(self):
        return self._handler_name

    @handler_name.setter
    def handler_name(self, name):
        self._handler_name = name

    @property
    def client(self):
        return self._client

    @client.setter
    def client(self, cloud_client):
        self._client = cloud_client

    @staticmethod
    def extract_zip_file_list(input_zip):
        input_zip = ZipFile(input_zip)
        return {name: input_zip.read(name) for name in input_zip.namelist()}

    @staticmethod
    def get_zip_file_to_temp_dir(input_zip, filename, temp_directory=None):
        if not temp_directory:
            temp_directory = mkdtemp()
        input_zip = ZipFile(input_zip)
        return input_zip.extract(filename, temp_directory)

    def list(self, remote_directory, depth=1):
        raise NotImplemented("method 'list' must be implemented in a Cloud Provider Handler")

    def prepare_zip_content_object(self, object_name, object_data, destination_base_dir: str = None):
        destination_base = destination_base_dir
        if not destination_base:
            destination_base = '/reMarkable2'
        logging.info(f"[Cloud Provider] trying to upload object {object_name} to {destination_base}")
        object_visible_name = None
        # try:
        #     object_metadata = load(open(join(self.base_path, object_name + '.metadata')))
        #     if 'visibleName' in object_metadata:
        #         object_visible_name = object_metadata['visibleName']
        # except FileNotFoundError:
        #     pass
        # logging.info(f"[Object Visible name]: {object_visible_name}")

        # TODO: evaluate size!
        # object_size = len(object_data)
        # object_size = object_size / 1024 / 1024
        # if object_size > self._object_size_limit:
        #     logging.info(
        #         f"[Cloud Provider]: Avoiding object, size ({object_size})"
        #         f" is higher than limit ({self.size_limit})."
        #     )
        #     return False

        tmp_dir = mkdtemp()
        structure = {
            'temp_dir': tmp_dir,
            'files': []
        }
        for object_in_zip in self.extract_zip_file_list(object_data):
            logging.info(f'[UP]: {object_in_zip}')
            _d = self.get_zip_file_to_temp_dir(object_data, object_in_zip, tmp_dir)
            structure['files'].append(object_in_zip)
        if len(structure['files']) > 0:
            return structure
        return False

    @staticmethod
    def construct_stored_file_info(
            uuid: str,
            version: int,
            modified_client_date: str,
            file_type: str,
            visible_name: str,
            current_page: int,
            parent_uuid: str,
            bookmarked=False
    ):
        _default_structure = {
            "ID": uuid,
            "Version": version,
            "Message": "",
            "Success": True,
            "BlobURLGet": "",
            "BlobURLGetExpires": "0001-01-01T00:00:00Z",
            "ModifiedClient": str(datetime.fromtimestamp(float(modified_client_date)/1000).strftime("%FT%H:%M:%S.%fZ")),
            "Type": file_type,
            "VissibleName": visible_name,
            "CurrentPage": current_page,
            "Bookmarked": bookmarked,
            "Parent": parent_uuid
        }
        return _default_structure

    def upload_unit(self, object_path, destination_base):
        raise NotImplemented("method 'upload_init' must be implemented in a Cloud Provider Handler")

    @property
    def size_limit(self):
        return self._object_size_limit

    @size_limit.setter
    def size_limit(self, limit_in_megabytes: int):
        self._object_size_limit = limit_in_megabytes

    @staticmethod
    def get_size(start_path):
        """
        Get size of a directory
        https://stackoverflow.com/a/1392549
        :param start_path: directory to sum
        :return: int size in bytes
        """
        total_size = 0
        for dir_path, dir_names, filenames in walk(start_path):
            for f in filenames:
                fp = join(dir_path, f)
                if not islink(fp):
                    total_size += getsize(fp)
        return total_size
