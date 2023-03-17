# Python
import os
import copy
import time
import json
import socket
import shutil
import string
import secrets
import zipfile
import tarfile

from io import BytesIO
from time import sleep
from datetime import datetime

# Flask
from flask import send_file

# GroundSeg Modules
from log import Log
from utils import Utils
from urbit_docker import UrbitDocker

default_pier_config = {
        "pier_name":"",
        "http_port":8080,
        "ames_port":34343,
        "loom_size":31,
        "urbit_version":"latest",
        "minio_version":"latest",
        "minio_password": "",
        "network":"none",
        "wg_url": "nan",
        "wg_http_port": None,
        "wg_ames_port": None,
        "wg_s3_port": None,
        "wg_console_port": None,
        "meld_schedule": False,
        "meld_frequency": 7,
        "meld_time": "0000",
        "meld_last": "0",
        "meld_next": "0",
        "boot_status": "boot",
        "custom_urbit_web": '',
        "custom_s3_web": '',
        "show_urbit_web": 'default'
        }


class Urbit:

    _volume_directory = '/var/lib/docker/volumes'

    def __init__(self, config, wg, minio):
        self.config_object = config
        self.config = config.config

        self.wg = wg
        self.minio = minio

        self.urb_docker = UrbitDocker()
        self._urbits = {}

        # Check if updater information is ready
        branch = self.config['updateBranch']
        count = 0
        while not self.config_object.update_avail:
            count += 1
            if count >= 30:
                break

            Log.log("Urbit: Updater information not yet ready. Checking in 3 seconds")
            sleep(3)

        # Updater Urbit information
        if self.config_object.update_avail:
            self.updater_info = self.config_object.update_payload['groundseg'][branch]['vere']

        self.start_all(self.config['piers'])

    # Start container
    def start(self, patp):
        if self.load_config(patp):
            if self.minio.start_minio(f"minio_{patp}", self._urbits[patp]):
                return self.urb_docker.start(self._urbits[patp],
                                             self.updater_info,
                                             self.config_object._arch,
                                             self._volume_directory)
        else:
            return "failed"

    def stop(self, patp):
        return self.urb_docker.stop(patp)
                

    # Delete Urbit Pier and MiniO
    def delete(self, patp):
        Log.log(f"{patp}: Attempting to delete all data")
        try:
            if self.urb_docker.delete(patp):

                endpoint = self.config['endpointUrl']
                api_version = self.config['apiVersion']
                url = f'https://{endpoint}/{api_version}'

                if self.config['wgRegistered']:
                    self.wg.delete_service(f'{patp}','urbit',url)
                    self.wg.delete_service(f's3.{patp}','minio',url)

                self.minio.delete(f"minio_{patp}")

                Log.log(f"{patp}: Deleting from system.json")
                self.config['piers'] = [i for i in self.config['piers'] if i != patp]
                self.config_object.save_config()

                Log.log(f"{patp}: Removing {patp}.json")
                os.remove(f"/opt/nativeplanet/groundseg/settings/pier/{patp}.json")

                self._urbits.pop(patp)
                Log.log(f"{patp}: Data removed from GroundSeg")

                return 200

        except Exception as e:
            Log.log(f"{patp}: Failed to delete data: {e}")

        return 400

    def export(self, patp):
        Log.log(f"{patp}: Attempting to export pier")
        c = self.urb_docker.get_container(patp)
        if c:
            if c.status == "running":
                self.stop(patp)

            file_name = f"{patp}.zip"
            memory_file = BytesIO()
            file_path=f"{self._volume_directory}/{patp}/_data/"

            Log.log(f"{patp}: Compressing pier")

            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(file_path):
                    arc_dir = root[root.find("_data/")+6:]
                    for file in files:
                        if file != 'conn.sock':
                            zipf.write(os.path.join(root, file), arcname=os.path.join(arc_dir,file))
                        else:
                            Log.log(f"{patp}: Skipping {file} while compressing")

            memory_file.seek(0)

            Log.log(f"{patp}: Pier successfully exported")
            return send_file(memory_file, download_name=file_name, as_attachment=True)

    # Start all valid containers
    def start_all(self, patps):
        Log.log("Urbit: Starting all ships")
        res = {"failed":[],"succeeded":[],"ignored":[],"invalid":[]}
        if len(patps) < 1:
            Log.log(f"Urbit: No ships detected in system.json! Skipping..")
            return True

        for p in patps:
            status = self.start(p)
            try:
                res[status].append(p)
            except Exception as e:
                Log.log(f"{p}: {e}")

        Log.log(f"Urbit: Start succeeded {res['succeeded']}")
        Log.log(f"Urbit: Start ignored {res['ignored']}")
        Log.log(f"Urbit: Start failed {res['failed']}")
        Log.log(f"Urbit: Patp invalid {res['invalid']}")

        return True

    # Return list of ship information
    def list_ships(self):
        urbits = []
        try:
            if len(self.config['piers']) > 0:
                for patp in self.config['piers']:
                    try:
                        u = dict()
                        c = self.urb_docker.get_container(patp)
                        if c:
                            cfg = self._urbits[patp]
                            u['name'] = patp
                            u['running'] = c.status == "running"
                            u['url'] = f'http://{socket.gethostname()}.local:{cfg["http_port"]}'
                            u['remote'] = False

                            if cfg['network'] == 'wireguard':
                                u['remote'] = True
                                u['url'] = f"https://{cfg['wg_url']}"

                                if cfg['show_urbit_web'] == 'alias':
                                    if cfg['custom_urbit_web']:
                                        u['url'] = f"https://{cfg['custom_urbit_web']}"

                            urbits.append(u)

                    except Exception as e:
                        Log.log(f"{patp}: Unable to get container information {e}")

        except Exception as e:
            Log.log(f"Urbit: Unable to list Urbit ships: {e}")

        return {'urbits': urbits}

    # Boot new pier from key
    def create(self, patp, key):
        Log.log(f"{patp}: Attempting to boot new urbit ship")
        try:
            if not Utils.check_patp(patp):
                raise Exception("Invalid @p")

            # TODO: Add check if exists, return prompt to user for further action
            
            # Get open ports
            http_port, ames_port = self.get_open_urbit_ports()

            # Generate config file for pier
            cfg = self.build_config(patp, http_port, ames_port)
            self._urbits[patp] = cfg
            self.save_config(patp)

            # Delete existing ship if exists
            if self.urb_docker.delete(patp):
                # Create the docker container
                if self.urb_docker.create(cfg, self.updater_info, self.config_object._arch, self._volume_directory, key):
                    if self.add_urbit(patp):
                        endpoint = self.config['endpointUrl']
                        api_version = self.config['apiVersion']
                        url = f"https://{endpoint}/{api_version}"
                        if self.register_urbit(patp, url):
                            if self.start(patp) == "succeeded":
                                return 200

        except Exception as e:
            Log.log(f"{patp}: Failed to boot new urbit ship: {e}")

        return 400

    def boot_existing(self, filename):
        patp = filename.split('.')[0]

        if Utils.check_patp(patp):
            Log.log(f"{patp}: Booting existing pier")
            extracted = self.extract_pier(filename)
            if extracted != "to-create":
                self.config_object.upload_status.pop(patp)
                return extracted

            created = self.create_existing(patp)
            if created != "succeeded":
                self.config_object.upload_status.pop(patp)
                return created
            self.config_object.upload_status[patp] = {'status':'done'}
            return 200

        return "File is invalid"


    def extract_pier(self, filename):
        patp = filename.split('.')[0]
        vol_dir = f'/var/lib/docker/volumes/{patp}'
        compressed_dir = f"{self.config_object.base_path}/uploaded/{patp}/{filename}"

        try:
            # Remove directory and make new empty one
            self.config_object.upload_status[patp] = {'status':'setup'}
            Log.log(f"{patp}: Removing existing volume")
            shutil.rmtree(f"{vol_dir}", ignore_errors=True)
            Log.log(f"{patp}: Creating volume directory")
            os.system(f'mkdir -p {vol_dir}/_data')

            # Begin extraction
            Log.log(f"{patp}: Extracting {filename}")

            # Zipfile
            if filename.endswith("zip"):
                with zipfile.ZipFile(compressed_dir) as zip_ref:
                    total_size = sum((file.file_size for file in zip_ref.infolist()))
                    self.config_object.upload_status[patp] = {
                            'status':'extracting',
                            'progress':{
                                'current':0,
                                'total': total_size
                                }
                            }
                    zip_ref.extractall(f"{vol_dir}/_data")

            # Tarball
            elif filename.endswith("tar.gz") or filename.endswith("tgz") or filename.endswith("tar"):
                with tarfile.open(compressed_dir, "r:gz") as tar_ref:
                    total_size = sum((member.size for member in tar_ref.getmembers()))
                    self.config_object.upload_status[patp] = {
                            'status':'extracting',
                            'progress':{
                                'current':0,
                                'total': total_size
                                }
                            }
                    tar_ref.extractall(f"{vol_dir}/_data")

        except Exception as e:
            Log.log(f"{patp}: Failed to extract {filename}: {e}")
            return "File extraction failed"

        try:
            self.config_object.upload_status[patp] = {'status':'cleaning'}
            shutil.rmtree(f"{self.config_object.base_path}/uploaded/{patp}", ignore_errors=True)
            Log.log(f"{patp}: Deleted {filename}")

        except Exception as e:
            Log.log(f"{patp}: Failed to remove {filename}: {e}")
            return f"Failed to remove {filename}"

        return "to-create"

    # Boot the newly uploaded pier
    def create_existing(self, patp):
        Log.log(f"{patp}: Attempting to boot new urbit ship")
        try:
            if not Utils.check_patp(patp):
                raise Exception("Invalid @p")

            self.config_object.upload_status[patp] = {'status':'booting'}
            # Get open ports
            http_port, ames_port = self.get_open_urbit_ports()

            # Generate config file for pier
            cfg = self.build_config(patp, http_port, ames_port)
            self._urbits[patp] = cfg
            self.save_config(patp)

            # Create the docker container
            if self.urb_docker.create(cfg, self.updater_info, self.config_object._arch, self._volume_directory, ""):
                if self.add_urbit(patp):
                    endpoint = self.config['endpointUrl']
                    api_version = self.config['apiVersion']
                    url = f"https://{endpoint}/{api_version}"
                    if self.register_urbit(patp, url):
                        return self.start(patp)

        except Exception as e:
            Log.log(f"{patp}: Failed to boot new urbit ship: {e}")

        return f"Failed to boot {patp}"

   # Return all details of Urbit ID
    def get_info(self, patp):
        # Check if Urbit Pier exists
        c = self.urb_docker.get_container(patp)
        if c:
            # If MinIO container exists
            containers = [patp]
            has_bucket = False
            if self.minio.minio_docker.get_container(f"minio_{patp}", False):
                containers.append(f"minio_{patp}")
                has_bucket = True

            cfg = self._urbits[patp]

            urbit = {
                "name": patp,
                "running": c.status == "running",
                "wgReg": self.config['wgRegistered'],
                "wgRunning": self.wg.is_running(),
                "autostart": cfg['boot_status'] != 'off',
                "meldOn": cfg['meld_schedule'],
                "timeNow": datetime.utcnow(),
                "frequency": cfg['meld_frequency'],
                "meldLast": datetime.fromtimestamp(int(cfg['meld_last'])),
                "meldNext": datetime.fromtimestamp(int(cfg['meld_next'])),
                "containers": containers,
                "meldHour": int(cfg['meld_time'][0:2]),
                "meldMinute": int(cfg['meld_time'][2:]),
                "remote": False,
                "urbitUrl": f"http://{socket.gethostname()}.local:{cfg['http_port']}",
                "minIOUrl": "",
                "minIOReg": True,
                "hasBucket": has_bucket,
                "loomSize": cfg['loom_size'],
                "showUrbWeb": 'default',
                "urbWebAlias": cfg['custom_urbit_web'],
                "s3WebAlias": cfg['custom_s3_web']
                }

            if cfg['network'] == 'wireguard':
                urbit['remote'] = True
                urbit['urbitUrl'] = f"https://{cfg['wg_url']}"

                if cfg['show_urbit_web'] == 'alias':
                    if cfg['custom_urbit_web']:
                        urbit['urbitUrl'] = f"https://{cfg['custom_urbit_web']}"
                        urbit['showUrbWeb'] = 'alias'

            if self.config['wgRegistered']:
                urbit['minIOUrl'] = f"https://console.s3.{cfg['wg_url']}"

            if cfg['minio_password'] == '':
                 urbit['minIOReg'] = False

            return urbit
        return 400


    # Get unused ports for Urbit
    def get_open_urbit_ports(self):
        http_port = 8080
        ames_port = 34343

        for u in self._urbits.values():
            if(u['http_port'] >= http_port):
                http_port = u['http_port']
            if(u['ames_port'] >= ames_port):
                ames_port = u['ames_port']

        return http_port+1, ames_port+1

    # Build new ship config
    def build_config(self, patp, http_port, ames_port):
        urb = copy.deepcopy(default_pier_config)

        urb['pier_name'] = patp
        urb['http_port'] = http_port
        urb['ames_port'] = ames_port

        return urb

    # Toggle Pier on or off
    def toggle_power(self, patp):
        Log.log(f"{patp}: Attempting to toggle container")
        c = self.urb_docker.get_container(patp)
        if c:
            cfg = self._urbits[patp]
            old_status = cfg['boot_status']
            if c.status == "running":
                if self.stop(patp):
                    if cfg['boot_status'] != 'off':
                        self._urbits[patp]['boot_status'] = 'noboot'
                        Log.log(f"{patp}: Boot status changed: {old_status} -> {self._urbits[patp]['boot_status']}")
                        self.save_config(patp)
                        return 200
            else:
                if cfg['boot_status'] != 'off':
                    self._urbits[patp]['boot_status'] = 'boot'
                    Log.log(f"{patp}: Boot status changed: {old_status} -> {self._urbits[patp]['boot_status']}")
                    self.save_config(patp)
                    if self.start(patp) == "succeeded":
                        return 200

        return 400

    # Get +code from Urbit
    def get_code(self, patp):
        code = ''
        lens_addr = self.get_loopback_addr(patp)
        try:
            f_data = {"source": {"dojo": "+code"}, "sink": {"stdout": None}}
            with open(f'{self._volume_directory}/{patp}/_data/code.json','w') as f :
                json.dump(f_data, f)

            command = f'curl -s -X POST -H "Content-Type: application/json" -d @code.json {lens_addr}'
            res = self.urb_docker.exec(patp, command)
            if res:
                code = res.output.decode('utf-8').strip().split('\\')[0][1:]

            os.remove(f'{self._volume_directory}/{patp}/_data/code.json')

        except Exception as e:
            Log.log(f"{patp}: Failed to get +code {e}")

        return code

    # Toggle Autostart
    def toggle_autostart(self, patp):
        Log.log(f"{patp}: Attempting to toggle autostart")
        c = self.urb_docker.get_container(patp)
        if c:
            try:
                cfg = self._urbits[patp]
                old_status = cfg['boot_status']
                if old_status == 'off':
                    if c.status == "running":
                        self._urbits[patp]['boot_status'] = 'boot'
                    else:
                        self._urbits[patp]['boot_status'] = 'noboot'
                else:
                    self._urbits[patp]['boot_status'] = 'off'

                self.save_config(patp)
                Log.log(f"{patp}: Boot status changed: {old_status} -> {self._urbits[patp]['boot_status']}")
                self.save_config(patp)
                return 200

            except Exception as e:
                Log.log(f"{patp}: Unable to toggle autostart: {e}")

        return 400

    def toggle_network(self, patp):
        Log.log(f"{patp}: Attempting to toggle network")

        wg_reg = self.config['wgRegistered']
        wg_is_running = self.wg.is_running()
        c = self.urb_docker.get_container(patp)

        if c:
            try:
                running = False
                if c.status == "running":
                    running = True
                
                old_network = self._urbits[patp]['network']

                self.urb_docker.remove_container(patp)

                if old_network == "none" and wg_reg and wg_is_running:
                    self._urbits[patp]['network'] = "wireguard"
                else:
                    self._urbits[patp]['network'] = "none"

                Log.log(f"{patp}: Network changed: {old_network} -> {self._urbits[patp]['network']}")
                self.save_config(patp)

                created = self.urb_docker.create(self._urbits[patp],
                                                 self.updater_info,
                                                 self.config_object._arch,
                                                 self._volume_directory)
                if created and running:
                    self.start(patp)

                return 200

            except Exception as e:
                Log.log(f"{patp}: Unable to change network: {e}")

        return 400

    def set_loom(self, patp, size):
        Log.log(f"{patp}: Attempting to set loom size")
        c = self.urb_docker.get_container(patp)
        if c:
            try:
                running = False
                if c.status == "running":
                    running = True
                
                old_loom = self._urbits[patp]['loom_size']
                self.urb_docker.remove_container(patp)
                self._urbits[patp]['loom_size'] = size
                self.save_config(patp)
                Log.log(f"{patp}: Loom size changed: {old_loom} -> {self._urbits[patp]['loom_size']}")

                created = self.urb_docker.create(self._urbits[patp],
                                                 self.updater_info,
                                                 self.config_object._arch,
                                                 self._volume_directory)
                if created and running:
                    self.start(patp)

                return 200

            except Exception as e:
                Log.log(f"{patp}: Unable to set loom size: {e}")

        return 400

    def schedule_meld(self, patp, freq, hour, minute):
        Log.log(f"{patp}: Attempting to schedule meld frequency")
        try:
            old_sched = self._urbits[patp]['meld_frequency']
            current_meld_next = datetime.fromtimestamp(int(self._urbits[patp]['meld_next']))
            time_replaced_meld_next = int(current_meld_next.replace(hour=hour, minute=minute).timestamp())

            day_difference = freq - self._urbits[patp]['meld_frequency']
            day = 60 * 60 * 24 * day_difference

            self._urbits[patp]['meld_next'] = str(day + time_replaced_meld_next)

            if hour < 10:
                hour = '0' + str(hour)
            else:
                hour = str(hour)

            if minute < 10:
                minute = '0' + str(minute)
            else:
                minute = str(minute)

            self._urbits[patp]['meld_time'] = hour + minute
            self._urbits[patp]['meld_frequency'] = int(freq)

            if self._urbits[patp]['meld_frequency'] > 1:
                days = "days"
            else:
                days = "day"

            Log.log(f"{patp}: Meld frequency changed: {old_sched} Days -> {self._urbits[patp]['meld_frequency']} {days}")
            self.save_config(patp)

            return 200

        except Exception as e:
            Log.log(f"{patp}: Unable to schedule meld: {e}")

        return 400

    def toggle_meld(self, patp):
        Log.log(f"{patp}: Attempting to toggle automatic meld")
        try:
            self._urbits[patp]['meld_schedule'] = not self._urbits[patp]['meld_schedule']
            Log.log(f"{patp}: Automatic meld changed: {not self._urbits[patp]['meld_schedule']} -> {self._urbits[patp]['meld_schedule']}")
            self.save_config(patp)

            try:
                now = int(datetime.utcnow().timestamp())
                if self._urbits[patp]['meld_schedule']:
                    if int(self._urbits[patp]['meld_next']) <= now:
                        self.send_pack_meld(patp)
            except:
                pass

        except Exception as e:
            Log.log(f"{patp}: Unable to toggle automatic meld: {e}")

        return 200

    def send_pack_meld(self, patp):
        lens_addr = self.get_loopback_addr(patp)
        if self.send_pack(patp, lens_addr):
            if self.send_meld(patp, lens_addr):
                return 200

        return 400

    def send_pack(self, patp, lens_addr):
        Log.log(f"{patp}: Attempting to send |pack")
        try:
            data = {"source": {"dojo": "+hood/pack"}, "sink": {"app": "hood"}}
            with open(f'{self._volume_directory}/{patp}/_data/pack.json','w') as f :
                json.dump(data, f)

            command = f'curl -s -X POST -H "Content-Type: application/json" -d @pack.json {lens_addr}'
            res = self.urb_docker.exec(patp, command)
            if res:
                os.remove(f'{self._volume_directory}/{patp}/_data/pack.json')
                Log.log(f"{patp}: |pack sent successfully")
                return True

        except Exception as e:
            Log.log(f"{patp}: Failed to send |pack: {e}")

        return False

    def send_meld(self, patp, lens_addr):
        Log.log(f"{patp}: Attempting to send |meld")
        try:
            data = {"source": {"dojo": "+hood/meld"}, "sink": {"app": "hood"}}
            with open(f'{self._volume_directory}/{patp}/_data/meld.json','w') as f :
                json.dump(data, f)

            command = f'curl -s -X POST -H "Content-Type: application/json" -d @meld.json {lens_addr}'
            res = self.urb_docker.exec(patp, command)
            if res:
                os.remove(f'{self._volume_directory}/{patp}/_data/meld.json')
                Log.log(f"{patp}: |meld sent successfully")

                now = datetime.utcnow()
                self._urbits[patp]['meld_last'] = str(int(now.timestamp()))

                hour, minute = self._urbits[patp]['meld_time'][0:2], self._urbits[patp]['meld_time'][2:]
                meld_next = int(now.replace(hour=int(hour), minute=int(minute), second=0).timestamp())
                day = 60 * 60 * 24 * self._urbits[patp]['meld_frequency']

                self._urbits[patp]['meld_next'] = str(meld_next + day)

                if self._urbits[patp]['meld_frequency'] > 1:
                    days = "days"
                else:
                    days = "day"

                Log.log(f"{patp}: Next meld in {self._urbits[patp]['meld_frequency']} {days}")
                self.save_config(patp)

                return True

        except Exception as e:
            Log.log(f"{patp}: Failed to send |meld")

        return False


    # Get looback address of Urbit Pier
    def get_loopback_addr(self, patp):
        log = self.urb_docker.full_logs(patp)
        if log:
            log_arr = log.decode("utf-8").split('\n')[::-1]
            substr = 'http: loopback live on'
            for ln in log_arr:
                if substr in ln:
                    return str(ln.split(' ')[-1])

    # Add urbit ship to GroundSeg
    def add_urbit(self, patp):
        Log.log(f"{patp}: Adding to system.json")
        try:
            self.config['piers'] = [i for i in self.config['piers'] if i != patp]
            self.config['piers'].append(patp)
            self.config_object.save_config()
            return True
        except Exception as e:
            Log.log(f"{patp}: Failed to add @p to system.json")

        return False

    # Register Wireguard for Urbit
    def register_urbit(self, patp, url):
        if self.config['wgRegistered']:
            Log.log(f"{patp}: Attempting to register anchor services")
            if self.wg.get_status(url):
                self.wg.update_wg_config(self.wg.anchor_data['conf'])

                # Define services
                urbit_web = False
                urbit_ames = False
                minio_svc = False
                minio_console = False
                minio_bucket = False

                # Check if service exists for patp
                for ep in self.wg.anchor_data['subdomains']:
                    ep_patp = ep['url'].split('.')[-3]
                    ep_svc = ep['svc_type']
                    if ep_patp == patp:
                        if ep_svc == 'urbit-web':
                            urbit_web = True
                        if ep_svc == 'urbit-ames':
                            urbit_ames = True
                        if ep_svc == 'minio':
                            minio_svc = True
                        if ep_svc == 'minio-console':
                            minio_console = True
                        if ep_svc == 'minio-bucket':
                            minio_bucket = True
 
                # One or more of the urbit services is not registered
                if not (urbit_web and urbit_ames):
                    Log.log(f"{patp}: Registering ship")
                    self.wg.register_service(f'{patp}', 'urbit', url)
 
                # One or more of the minio services is not registered
                if not (minio_svc and minio_console and minio_bucket):
                    Log.log(f"{patp}: Registering MinIO")
                    self.wg.register_service(f's3.{patp}', 'minio', url)

            svc_url = None
            http_port = None
            ames_port = None
            s3_port = None
            console_port = None
            tries = 1

            while None in [svc_url,http_port,ames_port,s3_port,console_port]:
                Log.log(f"{patp}: Checking anchor config if services are ready")
                if self.wg.get_status(url):
                    self.wg.update_wg_config(self.wg.anchor_data['conf'])

                Log.log(f"Anchor: {self.wg.anchor_data['subdomains']}")
                pub_url = '.'.join(self.config['endpointUrl'].split('.')[1:])

                for ep in self.wg.anchor_data['subdomains']:
                    if ep['status'] == 'ok':
                        if(f'{patp}.{pub_url}' == ep['url']):
                            svc_url = ep['url']
                            http_port = ep['port']
                        elif(f'ames.{patp}.{pub_url}' == ep['url']):
                            ames_port = ep['port']
                        elif(f'bucket.s3.{patp}.{pub_url}' == ep['url']):
                            s3_port = ep['port']
                        elif(f'console.s3.{patp}.{pub_url}' == ep['url']):
                            console_port = ep['port']
                    else:
                        t = tries * 2
                        Log.log(f"Anchor: {ep['svc_type']} not ready. Trying again in {t} seconds.")
                        time.sleep(t)
                        if tries <= 15:
                            tries = tries + 1
                        break

            return self.set_wireguard_network(patp, svc_url, http_port, ames_port, s3_port, console_port)

        return True

    def set_wireguard_network(self, patp, url, http_port, ames_port, s3_port, console_port):
        Log.log(f"{patp}: Setting wireguard information")
        try:
            self._urbits[patp]['wg_url'] = url
            self._urbits[patp]['wg_http_port'] = http_port
            self._urbits[patp]['wg_ames_port'] = ames_port
            self._urbits[patp]['wg_s3_port'] = s3_port
            self._urbits[patp]['wg_console_port'] = console_port
            return self.save_config(patp)
        except Exception as e:
            Log.log(f"{patp}: Failed to set wireguard information")
            return False

    # Update/Set Urbit S3 Endpoint
    def set_minio(self, patp):
        Log.log(f"{patp}: Attempting to set MinIO endpoint")
        acc = 'urbit_minio'
        secret = ''.join(secrets.choice(
            string.ascii_uppercase + 
            string.ascii_lowercase + 
            string.digits) for i in range(40))

        if self.minio.make_service_account(self._urbits[patp], patp, acc, secret):
            u = self._urbits[patp]
            endpoint = f"s3.{u['wg_url']}"
            if len(u['custom_s3_web']) > 0:
                endpoint = u['custom_s3_web']
            bucket = 'bucket'
            lens_port = self.get_loopback_addr(patp)
            try:
                return self.set_minio_endpoint(patp, endpoint, acc, secret, bucket, lens_port)

            except Exception as e:
                Log.log(f"{patp}: Failed to set MinIO endpoint: {e}")

        return 400

    def unlink_minio(self, patp):
        Log.log(f"{patp}: Attempting to unlink MinIO endpoint")
        try:
            lens_port = self.get_loopback_addr(patp)
            return self.unlink_minio_endpoint(patp, lens_port)
        except Exception as e:
            Log.log(f"{patp}: Failed to unlink MinIO endpoint: {e}")
        return 400

    def set_minio_endpoint(self, patp, endpoint, access_key, secret, bucket, lens_addr):
        self.send_poke(patp, 'set-endpoint', endpoint, lens_addr)
        self.send_poke(patp, 'set-access-key-id', access_key, lens_addr)
        self.send_poke(patp, 'set-secret-access-key', secret, lens_addr)
        self.send_poke(patp, 'set-current-bucket', bucket, lens_addr)

        return 200

    def unlink_minio_endpoint(self, patp, lens_addr):
        self.send_poke(patp, 'set-endpoint', '', lens_addr)
        self.send_poke(patp, 'set-access-key-id', '', lens_addr)
        self.send_poke(patp, 'set-secret-access-key', '', lens_addr)
        self.send_poke(patp, 'set-current-bucket', '', lens_addr)

        return 200

    def send_poke(self, patp, command, data, lens_addr):
        Log.log(f"{patp}: Attempting to send {command} poke")
        try:
            data = {"source": {"dojo": f"+landscape!s3-store/{command} '{data}'"}, "sink": {"app": "s3-store"}}
            with open(f'{self._volume_directory}/{patp}/_data/{command}.json','w') as f :
                json.dump(data, f)

            cmd = f'curl -s -X POST -H "Content-Type: application/json" -d @{command}.json {lens_addr}'
            res = self.urb_docker.exec(patp, cmd)
            if res:
                os.remove(f'{self._volume_directory}/{patp}/_data/{command}.json')
                Log.log(f"{patp}: {command} sent successfully")
                return True

        except Exception as e:
            Log.log(f"{patp}: Failed to send {command}: {e}")

        return False

    def update_wireguard_network(self, patp, url, http_port, ames_port, s3_port, console_port, alias):
        Log.log(f"{patp}: Attempting to update wireguard network")
        changed = False
        try:
            cfg = self._urbits[patp]
            if not cfg['wg_url'] == url:
                Log.log(f"{patp}: Wireguard URL changed from {cfg['wg_url']} to {url}")
                changed = True
                cfg['wg_url'] = url

            if not cfg['wg_http_port'] == http_port:
                Log.log(f"{patp}: Wireguard HTTP Port changed from {cfg['wg_http_port']} to {http_port}")
                changed = True
                cfg['wg_http_port'] = http_port

            if alias == "null":
                alias = ""
            if not cfg['custom_urbit_web'] == alias:
                Log.log(f"{patp}: Urbit Web Custom URL changed from {cfg['custom_urbit_web']} to {alias}")
                changed = True
                cfg['custom_urbit_web'] = alias

            if not cfg['wg_ames_port'] == ames_port:
                Log.log(f"{patp}: Wireguard Ames Port changed from {cfg['wg_ames_port']} to {ames_port}")
                changed = True
                cfg['wg_ames_port'] = ames_port

            if not cfg['wg_s3_port'] == s3_port:
                Log.log(f"{patp}: Wireguard S3 Port changed from {cfg['wg_s3_port']} to {s3_port}")
                changed = True
                cfg['wg_s3_port'] = s3_port

            if not cfg['wg_console_port'] == console_port:
                Log.log(f"{patp}: Wireguard Console Port changed from {cfg['wg_console_port']} to {console_port}")
                changed = True
                cfg['wg_console_port'] = console_port

            if changed:
                self.save_config(patp)

                if cfg['network'] != "none":
                    Log.log(f"{patp}: Rebuilding container")
                    running = False
                    self.minio.minio_docker.remove_container(f"minio_{patp}")
                    c = self.urb_docker.get_container(patp)
                    if c:
                        running = c.status == "running"
                        if self.urb_docker.remove_container(patp):
                            self.urb_docker.create(self._urbits[patp],
                                                   self.updater_info,
                                                   self.config_object._arch,
                                                   self._volume_directory,
                                                   '')
                    if running:
                        self.start(patp)
                    Log.log(f"{patp}: Wireguard network settings updated!")
            else:
                Log.log(f"{patp}: Nothing to change!")
        except Exception as e:
            Log.log(f"{patp}: Unable to update Wireguard network: {e}")
            return False
        return True

    # Custom Domain
    def custom_domain(self, patp, data):
        cfg = self._urbits[patp]
        svc = data['svc_type']
        alias = data['alias']
        op = data['operation']
        relink = data['relink']

        # Urbit URL
        if svc == 'urbit-web':
            if op == 'create':
                Log.log(f"{patp}: Attempting to register custom domain for {svc}")
                if self.dns_record(patp, cfg['wg_url'], alias):
                    if self.wg.handle_alias(patp, alias, 'post'):
                        self._urbits[patp]['custom_urbit_web'] = alias
                        self._urbits[patp]['show_urbit_web'] = 'alias'
                        if self.save_config(patp):
                            return 200
            elif op == 'delete':
                Log.log(f"{patp}: Attempting to delete custom domain for {svc}")
                if self.wg.handle_alias(patp, alias, 'delete'):
                    self._urbits[patp]['custom_urbit_web'] = ''
                    self._urbits[patp]['show_urbit_web'] = 'default'
                    if self.save_config(patp):
                        return 200

        # MinIO URL
        if svc == 'minio':
            if op == 'create':
                Log.log(f"{patp}: Attempting to register custom domain for {svc}")
                if self.dns_record(patp, f"s3.{cfg['wg_url']}", alias):
                    if self.wg.handle_alias(f"s3.{patp}", alias, 'post'):
                        self._urbits[patp]['custom_s3_web'] = alias
                        if self.save_config(patp):
                            if not relink:
                                return 200
                            else:
                                return self.set_minio(patp)

            elif op == 'delete':
                Log.log(f"{patp}: Attempting to delete custom domain for {svc}")
                if self.wg.handle_alias(f"s3.{patp}", alias, 'delete'):
                    self._urbits[patp]['custom_s3_web'] = ''
                    if self.save_config(patp):
                        if not relink:
                            return 200
                        else:
                            return self.set_minio(patp)
        return 400

    def dns_record(self, patp, real, mask):
        count = 0
        while count < 3:
            Log.log(f"{patp}: Checking DNS records")
            ori = False
            alias = False
            try:
                ori = socket.getaddrinfo(real, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
                Log.log(f"{patp}: {real} is {ori}")
            except:
                Log.log(f"{patp}: {real} has no record")

            try:
                alias = socket.getaddrinfo(mask, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
                Log.log(f"{patp}: {mask} is {alias}")
            except:
                Log.log(f"{patp}: {mask} has no record")

            if ori and alias:
                if ori == alias:
                    Log.log(f"{patp}: DNS records match")
                    return True

            count += 1
            time = count * 2
            Log.log(f"{patp}: Checking DNS record again in {time} seconds")
            sleep(time)

        Log.log(f"{patp}: DNS records do not match or does not exist")
        return False

    # Swap Display Url
    def swap_url(self, patp):
        try:
            old = self._urbits[patp]['show_urbit_web']

            if old == 'alias':
                self._urbits[patp]['show_urbit_web'] = 'default'
            else:
                self._urbits[patp]['show_urbit_web'] = 'alias'

            Log.log(f"{patp}: Urbit web display URL changed: {old} -> {self._urbits[patp]['show_urbit_web']}")
            self.save_config(patp)
            return 200
        except Exception as e:
            Log.log(f"{patp}: Failed to change urbit web display URL: {e}")
        return 400


    # Container logs
    def logs(self, patp):
        return self.urb_docker.full_logs(patp)

    def load_config(self, patp):
        try:
            with open(f"{self.config_object.base_path}/settings/pier/{patp}.json") as f:
                cfg = json.load(f)
                self._urbits[patp] = {**default_pier_config, **cfg}
                Log.log(f"{patp}: Config loaded")
                return True
        except Exception as e:
            Log.log(f"{patp}: Failed to load config: {e}")
            return False

    def save_config(self, patp):
        try:
            with open(f"{self.config_object.base_path}/settings/pier/{patp}.json", "w") as f:
                json.dump(self._urbits[patp], f, indent = 4)
                Log.log(f"{patp}: Config saved")
                return True
        except Exception as e:
            Log.log(f"{patp}: Failed to save config: {e}")
            return False
