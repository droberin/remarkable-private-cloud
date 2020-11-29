from os.path import isfile, isdir
from os.path import basename
from json import loads
from .reMarkableCloudProviderSkeleton import RemarkableCloudSkeleton
import logging
import owncloud


class RemarkableownCloudHandler(RemarkableCloudSkeleton):

    def configure(self, cloud_info):
        self.handler_name = 'ownCloud'
        self.configuration = cloud_info
        server_url = self.configuration['server']
        self.client = owncloud.Client(server_url)

    def login(self):
        logging.info(
            f"[Cloud Provider] trying to log in into '{self.configuration['server']}' "
            f"as '{self.configuration['username']}'"
        )
        self.client.login(self.configuration['username'], self.configuration['password'])
        return True

    def logout(self):
        logging.info(f"[Cloud Provider] trying to log out from '{self.configuration['server']}'")
        self.client.logout()

    def create_dir(self, cloud_dir):
        try:
            return self.client.mkdir(cloud_dir)
        except owncloud.owncloud.HTTPResponseError:
            return False

    def list(self, remote_directory, depth=1):
        _objects = []
        for remote_object in self.client.list(remote_directory, depth=1):
            if remote_object.path.endswith(".metadata"):
                uuid = basename(remote_object.path)[:-len(".metadata")]
                metadata = loads(str(self.client.get_file_contents(remote_object.path), encoding='utf-8'))
                _objects.append(
                    self.construct_stored_file_info(
                        uuid=uuid,
                        version=metadata['version'],
                        modified_client_date=metadata['lastModified'],
                        parent_uuid=metadata['parent'],
                        visible_name=metadata['visibleName'],
                        file_type=metadata['type'],
                        current_page=metadata['lastOpenedPage']
                    )
                )
        return _objects

    def upload_unit(self, unit, destination):
        if not isdir(unit) and not isfile(unit):
            # Ignore non existent files/dirs probably given from default skeleton object
            return False
        if destination != '' and not destination.endswith('/'):
            destination += '/'
        try:
            to_delete = destination + basename(unit)
            logging.debug(f"Trying to delete remote: {to_delete}")
            self.client.delete(to_delete)
        except owncloud.owncloud.HTTPResponseError:
            logging.debug(f"[PURGE] Unit {destination}/{basename(unit)} does not exist on server.")
        if isdir(unit):
            logging.debug(f"Putting dir {destination}{str(unit).split('/')[-1]}")
            return self.client.put_directory(destination, unit)
        elif isfile(unit):
            logging.debug(f"Putting file {destination}")
            _put_result = self.client.put_file_contents(f"{destination}", open(unit, 'rb'))
            return _put_result

    @property
    def size_limit(self):
        return self._directory_size_limit

    @size_limit.setter
    def size_limit(self, limit_in_megabytes: int):
        self._directory_size_limit = limit_in_megabytes
