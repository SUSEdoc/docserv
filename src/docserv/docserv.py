import hashlib
import json
import logging
import multiprocessing
import os
import queue
import resource
import shlex
import subprocess
import sys
import threading
import tempfile
import time
from configparser import ConfigParser as configparser

from docserv.bih import BuildInstructionHandler
from docserv.deliverable import Deliverable
from docserv.functions import print_help
from docserv.rest import RESTServer, ThreadedRESTServer


class DocservState:
    config = {}

    ###################################################
    #   The following section contains all dicts and  #
    #   queues that keep track of stuff to be built   #
    ###################################################
    #
    # 1. "queue" for build instructions from REST API
    #
    scheduled_build_instruction = {}
    scheduled_build_instruction_lock = threading.Lock()

    #
    # 2. When an item form the scheduled_build_instruction dict
    #    is taken up for processing, its information needs
    #    to be updated from the configuration. During that phase
    #    it remains in the scheduled_build_instructions dict but
    #    its key is added to the updating_build_instruction list.
    #    This also uses the scheduled_build_instruction_lock.
    updating_build_instruction = []

    #
    # 3.1 A dict that contains all BuildInstructionHandlers.
    #     This is the state in which documents are being
    #     build.
    #
    bih_dict = {}
    bih_dict_lock = threading.Lock()

    #
    # 3.2 A queue that contains BUILD_INSTRUCTION_ID. With the ID
    #     the workers will retrieve a Deliverable and build it.
    #
    bih_queue = queue.Queue()

    #
    # 4. When a BuildInstructionHandler is finished, its
    #    status is dumped into a dict and kept for the future.
    #
    past_builds = {}
    past_builds_lock = threading.Lock()

    # Access to git repositories must be controlled.
    # gitLocks is a dict of repoLock instances.
    gitLocks = {}
    gitLocksLock = threading.Lock()

    def __str__(self):
        return json.dumps(self.dict())

    def __repr__(self):
        return self.dict()

    def dict(self):
        """
        Create a list of all build instructions, queued, current and past.
        This is usually used to return the status on the REST API.
        """
        retval = []
        with self.scheduled_build_instruction_lock:
            for key in self.scheduled_build_instruction:
                try:
                    retval.append(self.scheduled_build_instruction[key])
                except AttributeError:
                    pass
        with self.bih_dict_lock:
            for key in self.bih_dict:
                try:
                    retval.append(self.bih_dict[key].dict())
                except AttributeError:
                    pass
        for key in self.past_builds:
            retval.append(self.past_builds[key])
        return retval

    def generate_id(self, build_instruction):
        """
        Generate a unique ID for a build instruction by hashing
        its values.
        """
        return hashlib.md5((build_instruction['target'] +
                            build_instruction['docset'] +
                            build_instruction['lang'] +
                            build_instruction['product']).encode('utf-8')
                           ).hexdigest()[:9]

    def queue_build_instruction(self, build_instruction):
        """
        Puts newly arrived build instructions in a dict that queues
        build instructions.
        """
        retval = False
        build_instruction['id'] = self.generate_id(build_instruction)
        if build_instruction['id'] in self.past_builds.keys():
            with self.past_builds_lock:
                build_instruction = self.past_builds.pop(
                    build_instruction['id'])
        with self.bih_dict_lock:
            if build_instruction['id'] not in self.bih_dict:
                with self.scheduled_build_instruction_lock:
                    if build_instruction['id'] not in self.scheduled_build_instruction:
                        self.scheduled_build_instruction[build_instruction['id']
                                                         ] = build_instruction
                        retval = True
        return retval

    def get_scheduled_build_instruction(self):
        """
        Get a build instruction that has been queued after input on
        the REST API.
        """
        with self.scheduled_build_instruction_lock:
            for key in self.scheduled_build_instruction:
                if key not in self.updating_build_instruction:
                    self.updating_build_instruction.append(key)
                    return self.scheduled_build_instruction[key]
        return None

    def remove_scheduled_build_instruction(self, build_instruction_id):
        """
        Remove a build instruction from the queued dictionary. This
        usually means that a BuildInstructionHandler was created and
        documents are being built.
        """
        with self.scheduled_build_instruction_lock:
            self.updating_build_instruction.remove(build_instruction_id)
            self.scheduled_build_instruction.pop(build_instruction_id)

    def abort_build_instruction(self, build_instruction_id):
        """
        If the initialization of the BuildInstructionHandler fails,
        move the build instruction to the past_builds dict and remove
        it from the queued build instructions.
        """
        logger.info("Aborting build instruction %s", build_instruction_id)
        with self.scheduled_build_instruction_lock:
            self.updating_build_instruction.remove(build_instruction_id)
            build_instruction = self.scheduled_build_instruction.pop(
                build_instruction_id, None)
        if build_instruction is None:
            with self.bih_dict_lock:
                build_instruction = self.bih_dict.pop(
                    build_instruction_id).dict()
        if build_instruction is not None:
            with self.past_builds_lock:
                self.past_builds[build_instruction_id] = build_instruction

    def finish_build_instruction(self, build_instruction_id):
        """
        After all deliverables are finished, dump a dict of the
        BuildInstructionHandler into the past_builds dict.
        """
        logger.info("Finished build instruction %s", build_instruction_id)
        self.bih_dict[build_instruction_id].cleanup()
        with self.bih_dict_lock:
            build_instruction = self.bih_dict.pop(build_instruction_id)
        with self.past_builds_lock:
            self.past_builds[build_instruction_id] = build_instruction.dict()

    def get_deliverable(self, thread_id):
        """
        Get an ID from the bih_queue (currently building BIHs). With that
        get a deliverable from the BIH itself. If no more deliverables are
        available, the BIH is finished.
        """
        try:
            build_instruction_id = self.bih_queue.get(False)
        except queue.Empty:
            return None
        else:
            deliverable = self.bih_dict[build_instruction_id].get_deliverable()
            if deliverable == 'done':
                self.finish_build_instruction(build_instruction_id)
                deliverable = None
            else:  # build instruction is not yet finished, put its ID back on the queue
                self.bih_queue.put(build_instruction_id)
        return deliverable

    def save_state(self):
        """
        Save status to JSON file.
        The JSON file usually resides in /var/cache/docserv/[SERVER_NAME].json
        """
        f = open(os.path.join(CACHE_DIR, self.config['server']['name'] + '.json'), "w")
        f.write(json.dumps(self.dict()))

    def load_state(self):
        """
        Load status from JSON file.
        The JSON file usually resides in /var/cache/docserv/[SERVER_NAME].json
        """
        logger.info("Reading previous state.")
        filepath = os.path.join(CACHE_DIR, self.config['server']['name'] + '.json')
        if os.path.isfile(filepath):
            file = open(filepath, "r")
            try:
                state = json.loads(file.read())
            except json.decoder.JSONDecodeError:
                return False
            for build_instruction in state:
                if ('building' in build_instruction and len(build_instruction['building']) > 0) or ('open' in build_instruction and len(build_instruction['open']) > 0):
                    self.queue_build_instruction(build_instruction)
                else:
                    self.past_builds[build_instruction['id']
                                     ] = build_instruction
            return True
        return False

    def parse_build_instruction(self, thread_id):
        build_instruction = self.get_scheduled_build_instruction()
        if build_instruction is not None:
            myBIH = BuildInstructionHandler(
                build_instruction, self.config, self.stitch_tmp_dir, self.gitLocks, self.gitLocksLock, thread_id)
            # If the initialization failed, immediately delete the BuildInstructionHandler
            if myBIH.initialized == False:
                self.abort_build_instruction(build_instruction['id'])
                return
            myBIH.generate_deliverables()
            self.remove_scheduled_build_instruction(build_instruction['id'])
            with self.bih_dict_lock:
                self.bih_dict[build_instruction['id']] = myBIH
            self.bih_queue.put(build_instruction['id'])


class DocservConfig:
    """
    Class for handling the .ini configuration file.
    """

    def parse_config(self, argv):
        config = configparser()
        if len(argv) == 1:
            config_file = "docserv"
        else:
            config_file = argv[1]
        config_path=os.path.join(CONF_DIR, config_file + '.ini')
        logger.info("Reading %s", config_path)
        config.read(config_path)
        self.config = {}
        try:
            self.config['server'] = {}
            self.config['server']['name'] = config_file
            self.config['server']['loglevel'] = int(config['server']['loglevel'])
            self.config['server']['host'] = config['server']['host']
            self.config['server']['port'] = int(config['server']['port'])
            self.config['server']['repo_dir'] = config['server']['repo_dir']
            self.config['server']['temp_repo_dir'] = config['server']['temp_repo_dir']
            self.config['server']['valid_languages'] = config['server']['valid_languages']
            self.config['server']['max_threads'] = int(config['server']['max_threads'])
            self.config['targets'] = {}
            for section in config.sections():
                if not str(section).startswith("target_"):
                    continue
                self.config['targets'][config[section]['name']] = {}
                self.config['targets'][config[section]['name']]['name'] = config[section]['name']
                self.config['targets'][config[section]['name']]['template_dir'] = config[section]['template_dir']
                self.config['targets'][config[section]['name']]['active'] = config[section]['active']
                self.config['targets'][config[section]['name']]['draft'] = config[section]['draft']
                self.config['targets'][config[section]['name']]['remarks'] = config[section]['remarks']
                self.config['targets'][config[section]['name']]['meta'] = config[section]['meta']
                self.config['targets'][config[section]['name']]['default_xslt_params'] = config[section]['default_xslt_params']
                self.config['targets'][config[section]['name']]['target_path'] = config[section]['target_path']
                self.config['targets'][config[section]['name']]['backup_path'] = config[section]['backup_path']
                self.config['targets'][config[section]['name']]['config_dir'] = config[section]['config_dir']
                self.config['targets'][config[section]['name']]['languages'] = config[section]['languages']
                self.config['targets'][config[section]['name']]['default_lang'] = config[section]['default_lang']
                self.config['targets'][config[section]['name']]['omit_default_lang_path'] = config[section]['omit_default_lang_path']
                self.config['targets'][config[section]['name']]['internal'] = config[section]['internal']
                self.config['targets'][config[section]['name']]['zip_formats'] = config[section]['zip_formats']
                self.config['targets'][config[section]['name']]['server_base_path'] = config[section]['server_base_path']
                self.config['targets'][config[section]['name']]['canonical_url_domain'] = config[section]['canonical_url_domain']
                self.config['targets'][config[section]['name']]['htaccess'] = config[section]['htaccess']
                self.config['targets'][config[section]['name']]['favicon'] = config[section]['favicon']
        except KeyError as error:
            logger.warning(
                "Invalid configuration file, missing configuration key '%s'. Exiting.", error)
            sys.exit(1)


class Docserv(DocservState, DocservConfig):
    """
    This class creates worker threads and starts the REST API.
    """
    end_all = queue.Queue()

    def __init__(self, argv):
        self.parse_config(argv)
        LOGLEVELS = {0: logging.WARNING,
                     1: logging.INFO,
                     2: logging.DEBUG,
                     }
        logger.setLevel(LOGLEVELS[self.config['server']['loglevel']])
        self.load_state()

    def start(self):
        """
        Create worker and REST API threads.
        """

        if multiprocessing.cpu_count() < self.config['server']['max_threads']:
            self.config['server']['max_threads'] = multiprocessing.cpu_count()
            logger.info("Scaling down the number of threads to %i, to avoid creating more threads than there are CPUs.",
                self.config['server']['max_threads'])

        # Increase number of files that can be opened on the system, otherwise
        # we tend to run into issues. With 12 threads, we tend to hover around
        # ~1500 within our process (and more within the Docker containers
        # supposedly), but the default is just 1024 per process.

        # This is a guess, from looking at the average SLE run
        files_per_thread = 200
        wanted_threads = self.config['server']['max_threads']
        min_safe_file_limit = files_per_thread * wanted_threads

        # We will only get 4096 anyway. This is what we dream of, but let's not
        # dream too big.
        ideal_file_limit = 8192

        # The following is the equivalent of calling ulimit -n & ulimit -Hn
        file_limit_soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        file_limit_hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
        new_file_limit = ideal_file_limit
        if file_limits[1] < ideal_file_limit:
            new_file_limit = file_limit_hard
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_file_limit, file_limits[1]) )
        except ValueError:
            logger.warning("Could not update limit on open files for process to %i (from %i).",
                new_file_limit, file_limits[0])

        # Ask again and scale down the number of threads if it's not enough
        file_limit_soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        if resource.getrlimit(file_limit_soft < min_safe_file_limit:
            self.config['server']['max_threads'] = int(file_limit_soft / files_per_thread)
            logger.warning("Scaling down the number of threads to %i to avoid opening too many files.",
                self.config['server']['max_threads'])

        try:
            # After starting docserv, make sure to stitch as the first thing,
            # this increases startup time but means that as long as the config
            # does not change, we don't have to do another complete validation
            self.stitch_tmp_dir = tempfile.mkdtemp(prefix='docserv_stitch_')

            # Notably, the config dir can be different for different targets.
            # So, stitch for each.
            for target in self.config['targets']:
                stitch_tmp_file = os.path.join(self.stitch_tmp_dir,
                    ('productconfig_simplified_%s.xml' % target))
                # Largely copypasta from bih.py cuz I dunno how to share stuff
                logger.debug("Stitching XML config directory to %s",
                             stitch_tmp_file)
                # Don't use --revalidate-only parameter: after starting we
                # really want to make sure that the config is alright.
                cmd = '%s --simplify --valid-languages="%s" %s %s' % (
                    os.path.join(BIN_DIR, 'docserv-stitch'),
                    self.config['server']['valid_languages'],
                    self.config['targets'][target]['config_dir'],
                    stitch_tmp_file)
                logger.debug("Stitching command: %s", cmd)
                cmd = shlex.split(cmd)
                s = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                self.out, self.err = s.communicate()
                rc = int(s.returncode)
                if rc == 0:
                    logger.debug("Stitching of %s successful",
                                 self.config['targets'][target]['config_dir'])
                else:
                    logger.warning("Stitching of %s failed!",
                                   self.config['targets'][target]['config_dir'])
                    logger.warning("Stitching STDOUT: %s", self.out.decode('utf-8'))
                    logger.warning("Stitching STDERR: %s", self.err.decode('utf-8'))
                # End copypasta

            thread_receive = threading.Thread(target=self.listen)
            thread_receive.start()
            workers = []
            for i in range(0, min([os.cpu_count(), self.config['server']['max_threads']])):
                logger.info("Starting build thread %i", i)
                worker = threading.Thread(target=self.worker, args=(i,))
                worker.start()
                workers.append(worker)
            # to have a clean shutdown, wait for all threads to finish
            thread_receive.join()
        except KeyboardInterrupt:
            self.exit()
        for worker in workers:
            worker.join()
        self.rest.shutdown()
        self.save_state()

    def exit(self):
        logger.warning(
            "Received SIGINT. Telling all threads to end. Please wait.")
        self.end_all.put("now")

    def worker(self, thread_id):
        while(True):
            # 1. parse input from rest api and put the instance of the doc class on the currently building queue
            self.parse_build_instruction(thread_id)

            # 2. get doc from currently_building queue and then a deliverable from doc.
            #    after that, put doc back on the currently building queue. unless it was
            #    the last deliverable.
            deliverable = self.get_deliverable(thread_id)
            if deliverable is not None:
                deliverable.run(thread_id)

            # 3. end thread if sigint
            if not self.end_all.empty():
                return True

            # 4. wait for a short while, then repeat
            time.sleep(0.1)

            # Thread 0 is frequently saving the state
            if thread_id == 0:
                self.save_state()

    def listen(self):
        server_address = (self.config['server']['host'], int(
            self.config['server']['port']))
        self.rest = ThreadedRESTServer(server_address, RESTServer, self)
        self.rest.serve_forever()
        return True


logger = logging.getLogger('docserv')
logger.setLevel(logging.INFO)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

BIN_DIR = os.getenv('DOCSERV_BIN_DIR', "/usr/bin/")
CONF_DIR = os.getenv('DOCSERV_CONFIG_DIR', "/etc/docserv/")
SHARE_DIR = os.getenv('DOCSERV_SHARE_DIR', "/usr/share/docserv/")
CACHE_DIR = os.getenv('DOCSERV_CACHE_DIR', "/var/cache/docserv/")


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
    else:
        docserv = Docserv(sys.argv)
        docserv.start()
        sys.exit(0)


main()
