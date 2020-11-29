import sys
import m2crypto_ca
import logging
import coloredlogs
from os.path import isfile, isdir
from shutil import copyfile
from json import loads, dumps
from os import makedirs, environ
from os.path import join
from bottle import route, HTTPResponse, run, request, response
from yaml import safe_load
from owncloud.owncloud import HTTPResponseError as OCSResponseError
from datetime import datetime, timedelta
from zipfile import ZipFile
from uuid import uuid4
# Import all existing storage providers
from cloudproviders import *


# @route('/token/json/2/device/new', method='ANY')


@route('/ca', method='ANY')
def get_ca():
    response.content_type = 'text/plain; charset=UTF8'
    return open('certs/rmCloudCA.pem').read()
    # return static_file('rmCloudCA.pem', 'certs')


@route('/', method='ANY')
def main():
    response.content_type = 'text/plain; charset=UTF8'
    return f'''
# This is an own instance of myOwnReMarkableCloud.
## Get yours at https://github.com/blah/remarkable-cloud-server
##
#### Info for Developers only:
# For easier debugging:
# sudo iptables -t nat -I PREROUTING -i enp27s0 -p tcp --dport 443 -s 192.168.1.0/24 -j REDIRECT --to-port 8000
# sudo iptables -t nat -I PREROUTING -p tcp --dport 443 -s 10.11.99.1/32 -j REDIRECT --to-port 8000
# So you don't need to run it as root.

## Setup this CA in your reMarkable device using these commands on its shell through SSH connection.
wget -O myOwnReMarkableCloud.crt https://{request.get_header('host')}/ca

# or if not using https
wget -O myOwnReMarkableCloud.crt http://{request.get_header('host')}/ca

# Add these entries to your /etc/hosts if they are not there already
YOUR_SERVER_IP_ADDRESS    document-storage-production-dot-remarkable-production.appspot.com
YOUR_SERVER_IP_ADDRESS    webapp-production-dot-remarkable-production.appspot.com

# Copy this CA to your reMarkable 
mkdir -p /usr/local/share/ca-certificates/
cp myOwnReMarkableCloud.crt /usr/local/share/ca-certificates/

# Update your device info!
update-ca-certificates

# Now restart main process (or reboot device)
systemctl restart xochitl
'''


def account_exists(account_name):
    if account_name not in configuration['accounts']:
        logger.info(f'Account not found {account_name}')
        return False
    logger.info(f'Account found {account_name[:39]}')
    return True


def get_account_for_device_token(token):
    if token in configuration['device_map']:
        return configuration['device_map'][token]
    else:
        return False


def reload_config():
    global configuration
    configuration = safe_load(open('etc/known_devices.yaml'))
    # TODO: may need closing already existing sessions!


def grant_session(account, token):
    if not account_exists(account):
        return False
    session_data = configuration['accounts'][account]
    logger.debug(f"session name: {session_data}")
    if session_data['temp_token'] not in cloud_sessions.keys():
        cloud_sessions[token] = session_data
        cloud_provider_handler_name = session_data['cloud']['provider']
        try:
            # TODO: Call Security! we are using an unchecked eval call!
            cloud_sessions[token]["provider"] = eval(cloud_provider_handler_name)()
        except NameError:
            logger.warning(f"[Cloud handler] «{cloud_provider_handler_name}» is not a valid provider")
            return False
        provider = cloud_sessions[token]["provider"]
        provider.configure(session_data['cloud'])
    return cloud_sessions[token]


@route('/admin/reload', method='GET')
def admin_reload():
    reload_config()
    # add some more stuff to do later...


def get_authorization(request_object):
    try:
        authorization = request_object.get_header("Authorization")
    except KeyError:
        return
    if str(authorization)[:7] == 'Bearer ' and len(authorization) > 7:
        authorization = str(authorization).split(' ')[1]
    return authorization


@route('/token/json/2/device/new', method='POST')
def register_new_device():
    logger.warning(request)
    pass


@route('/token/json/2/user/new', method='POST')
def get_new_user_token():
    authorization = get_authorization(request)
    if not authorization:
        return HTTPResponse(status=401)
    account_name = get_account_for_device_token(authorization)
    session = grant_session(account_name, token=authorization)
    if not session:
        return HTTPResponse(status=401)
    cloud = session['provider']
    login_status = cloud.login()
    if not login_status:
        logger.critical(
            f"[Cloud Provider]: storage config for account {account_name} "
            f"({session['owner']}) not correct. Denying login."
        )
        return HTTPResponse(status=401)
    logger.info(
        f"[Cloud Provider][{session['cloud']['provider']}]: "
        f"Token matches account {account_name} and logged into Storage endpoint."
    )
    return session['temp_token']


@route('/document-storage/json/2/upload/request', method='PUT')
def post_file():
    token = get_authorization(request_object=request)
    if not token:
        logger.warning("Session not found")
        return HTTPResponse(status=401)
    session = grant_session(
        get_account_for_device_token(configuration['token_to_device_map'][token]),
        configuration['token_to_device_map'][token]
    )
    token = configuration['token_to_device_map'][token]
    cloud_sessions[token] = session
    if token not in cloud_sessions:
        logger.warning("token not found, mate")
        return HTTPResponse(status=401)
    logger.warning(f"[{cloud_sessions[token]['owner']}] Requesting file(s) upload.")
    files_to_upload = loads(str(request.body.read(), encoding='utf-8'))
    cloud = cloud_sessions[token]['provider']
    _upload_constructor = []
    for count, file in enumerate(files_to_upload):
        _message = ''
        logger.warning(f'[#{count}] [{file["ID"]}] (v{file["Version"]})')
        _version = 1
        _success = False
        try:
            contents = loads(cloud.client.get_file_contents(f"reMarkable2/{file['ID']}.metadata"))
            _version = contents['Version']
        except OCSResponseError:
            _version = 1
        if _version <= file['Version']:
            _success = True
        else:
            _message = 'File in Cloud is newer'

        _gen_uuid = str(uuid4()) + str(uuid4()) + str(uuid4())
        expecting_payloads[_gen_uuid] = token
        blob_url_put = f'https://{request.get_header("host")}/putblob/{file["ID"]}/{_gen_uuid}'
        # blob_url_put = f'http://127.0.0.1:8888/putblob/{file["ID"]}/{_gen_uuid}'
        _upload_constructor.append(
            {
                'ID': file['ID'],
                'Version': _version,
                'Message': _message,
                'Success': _success,
                'BlobURLPut': blob_url_put,
                'BlobURLPutExpires': str((datetime.now() + timedelta(minutes=10)).strftime("%FT%H:%M:%S.%fZ"))
            }
        )
        logger.warning(f'Expect upload at: {blob_url_put}')
    logger.debug(_upload_constructor)
    return dumps(_upload_constructor)


def extract_zip(input_zip):
    input_zip = ZipFile(input_zip)
    return {name: input_zip.read(name) for name in input_zip.namelist()}


def extract_zip_file(input_zip, filename):
    input_zip = ZipFile(input_zip)
    return input_zip.extract(filename)


@route('/putblob/<uuid>/<expecting_uuid>', method='PUT')
def upload_blob(uuid: str, expecting_uuid: str):
    authorization = get_authorization(request)
    token = configuration['token_to_device_map'][authorization]
    session = cloud_sessions[token]
    if not session:
        return HTTPResponse(status=401)
    cloud = session['provider']
    logger.info(f'[Storage Provider]: storing {uuid} for user {session["owner"]}')
    upload_objects = cloud.prepare_zip_content_object(object_name=uuid, object_data=request.files.get('file'))
    _count = []
    _tmp_dir = upload_objects['temp_dir']
    for file_to_upload in upload_objects['files']:
        _count.append(cloud.upload_unit(join(_tmp_dir, file_to_upload), f'remarKable2/{file_to_upload}'))
    logger.info(_count)
    return


@route('/document-storage/json/2/docs', method='GET')
@route('/document-storage/json/2/docs/<uuid>', method='GET')
def list_documents(uuid=None):
    look_for = 'reMarkable2/'
    if uuid:
        look_for += uuid
    user_token = get_authorization(request)
    if not user_token:
        logger.warning("Session not found")
        return HTTPResponse(status=401)
    if user_token not in configuration['token_to_device_map']:
        logger.warning("User token not found")
        return HTTPResponse(status=401)
    token = configuration['token_to_device_map'][user_token]
    cloud = cloud_sessions[token]['provider']
    cloud.login()
    document_list = cloud.list(look_for, depth=1)
    logger.debug(dumps(document_list))
    return dumps(document_list)


@route('/', defaults={'path': ''}, method='ANY')
@route('/<path:path>', method='ANY')
def catch_all(path):
    logger.critical(f'[{request.method}] path: {path}')
    return f'[{request.method}] Path "{path}" is unknown'


if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    coloredlogs.install('INFO', logger=logger)

    # First argument would be used as listening port, if specified
    if sys.argv[1:]:
        port = int(sys.argv[1])
    else:
        port = 8000
    ca_key_file = f'certs/rmCloudCA.key'
    ca_cert_file = f'certs/rmCloudCA.pem'
    server_key_file = f'certs/rmCloudServer.key'
    server_cert_file = f'certs/rmCloudServer.pem'
    if not isdir('certs'):
        logger.warning("No certs dir found. Creating it.")
        makedirs('certs')
    if not isfile(ca_cert_file) or not isfile(ca_key_file):
        logger.warning("No CA cert files found. Creating them.")
        _ca_cert_file, _ca_key_file = m2crypto_ca.mk_temporary_cacert()
        copyfile(str(_ca_cert_file.name), ca_cert_file)
        copyfile(str(_ca_key_file.name), ca_key_file)

    if not isfile(server_cert_file) or not isfile(server_key_file):
        logger.warning("No Server cert files found. Creating them.")
        _server_cert_file, _server_key_file = m2crypto_ca.mk_temporary_cert(
            cacert_file=ca_cert_file,
            ca_key_file=ca_key_file,
            cn='*.appspot.com'
        )
        copyfile(str(_server_cert_file.name), server_cert_file)
        copyfile(str(_server_key_file.name), server_key_file)

    # release this module, not doing any good anymore. :)
    del m2crypto_ca

    configuration = safe_load(open('etc/known_devices.yaml'))

    cloud_sessions = {}
    expecting_payloads = {}

    # run servah!
    if environ.get('NON_SSL_SERVER'):
        run(host='0.0.0.0', port=port, server='gunicorn', debug=True)
    else:
        run(
            host='0.0.0.0',
            port=port,
            server='gunicorn',
            debug=environ.get('DEBUG', False),
            keyfile=server_key_file,
            certfile=server_cert_file
        )
