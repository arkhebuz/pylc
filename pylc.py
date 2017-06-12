#!/usr/bin/env python3
"""
Main pylc module, holds core functionality, library for pylccommand and pylcworker.

Docstring Status:
 - To Do

Note that this code follows pep8 very loosely...
"""

import os
import logging
import subprocess

import lxc
import yaml
import psutil
from lockfile import LockFile



def add_spawn_worker(aclass):
    def spawn_worker(self):
        self.logger.info("Spawning new worker for container %s, display %s",
                         self.CFG.container, self.CFG.display)
        ACL_COMM = [self.CFG.python3_binary_patch, self.CFG.pylc_catalog + '/pylcworker.py',
                    self.CFG.container, str(self.CFG.display) ]
        subprocess.Popen(ACL_COMM,
                         stdout=open('{0}/xpra-{1}.log'.format(self.CFG.log_files_catalog,
                                                               self.CFG.container), 'a'),
                         stderr=subprocess.STDOUT,
                         preexec_fn=os.setpgrp)
    setattr(aclass, 'spawn_worker', spawn_worker)
    return aclass


def set_config(aclass):
    """Set parameters stored in config file as aclass attributes."""
    homedir = os.environ['HOME']
    conf_file = "{0}/.pylc/config.yml".format(homedir)
    with open(conf_file, 'r') as stream:
        yaml_dict = yaml.safe_load(stream)
    for k, v in yaml_dict.items():
        setattr(aclass, k, v)
    return aclass

class ConfigRepr(type):
    def __repr__(cls):
        return r'<Config %s>' % cls.__dict__

@set_config
class Config(metaclass=ConfigRepr):
    @classmethod
    def set_derived_parameters(cls):
        setattr(cls, 'COMMFILE', cls.state_files_catalog+'/{0}.yml'.format(cls.container))
        try:
            cls.display
        except AttributeError:
            pass
        else:
            setattr(cls, 'xpra', 'xpra-{0}'.format(cls.display))
            setattr(cls, 'xpra_worker', 'xpra-{0}-worker'.format(cls.display))


class InSanity(object):
    """
    Class for basic sanity checking of the YAML-written state file.

    Example usage:
    >>> IS = InSanity(Config, logger=logging.getLogger(__name__))
    >>> IS.check()
    """

    def __init__(self, CFG, logger=None):
        """
        logger -- logger (default none). If none is leaved, new logger
                  is created, pringting to stdout with DEBUG level.
        """
        self.CFG = CFG
        self.c = lxc.Container(self.CFG.container)
        assert(self.c.defined)
        self.sane = True
        self.live = 0
        # Either recive logger or get one yourself and set
        # its level to debug for commandline '-c' option
        self.logger = logger or logging.getLogger("InSanity")
        if not logger:
            self.logger.setLevel(logging.DEBUG)
            # create console handler
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            # create formatter and add it to the handlers
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            # add the handlers to logger
            self.logger.addHandler(ch)
            # Dont propagate messages upstream in hierarchy (no double output)
            self.logger.propagate = False

    def check(self):
        """
        Check for the insanity of the values in YAML state file.

        Look for three situations meaning insanity and return False
        if one/two/all happen:
        - pid is written in state file, but a process with that pid doesn't exist
        - pid is written in state file, but a process with that pid is a ZOMBIE
        - container is running, but there are no live pids in it's state file

        When True is returned, the YAML values may or MAY NOT be sane.
        """
        self.sane = True
        self.live = 0
        self.logger.debug("Insanity check on %s...", self.CFG.COMMFILE)
        shit_msg = "There's some really weried shit in {0}".format(self.CFG.COMMFILE)

        try:
            with LockFile(self.CFG.COMMFILE) as lock:                        #pylint: disable=W0612
                with open(self.CFG.COMMFILE, 'r') as stream:
                    yaml_dict = yaml.safe_load(stream)

        except FileNotFoundError:
            self.logger.debug("FILE NOT FOUND. First run?")

        else:
            self.logger.debug('Pid Existence:')
            for k, v in yaml_dict.items():
                self.logger.debug("  "+k+":")
                if v is None or v == []:
                    # There are no registered pid(s) for given key,
                    # Nothing to check
                    pass
                elif isinstance(v, int):
                    self._check_pair(k, v)
                elif isinstance(v, list):
                    for vv in v:
                        if isinstance(vv, int):
                            self._check_pair(k, vv)
                        else:
                            raise RuntimeError(shit_msg)
                elif v == 'DISABLED':
                    self.logger.debug("          DISABLED")
                else:
                    raise RuntimeError(shit_msg)

            if self.c.state == "RUNNING" and self.live == 0:
                self.logger.error(("Container %s is running, but no precesses "
                                   "are registered in state file %s"),
                                  self.CFG.container,
                                  self.CFG.COMMFILE)
                self.sane = False

        return self.sane

    def _check_pair(self, k, v):
        """Check if process with pid `v` exists."""
        try:
            proc = psutil.Process(v)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Insanity detected
            self.logger.error(("Process '%s' for '%s', section '%s' "
                               "doesn't exist (state file: %s)"),
                              v, self.CFG.container,
                              k, self.CFG.COMMFILE)
            self.sane = False
        else:
            # We should check if its a zombie proces anyway
            if proc.status() == psutil.STATUS_ZOMBIE:
                # Zombie process!
                self.logger.error(("Process '%s' for '%s', section '%s' "
                                   "is a ZOMBIE (state file: %s)"),
                                  v, self.CFG.container,
                                  k, self.CFG.COMMFILE)
                self.sane = False
            else:
                self.live += 1
                self.logger.debug("          {0}: True".format(v))


class StartStop(object):
    """
    Context manager respecting YAML state file for starting/stopping containers.
    """
    def __init__(self, CFG):
        self.CFG = CFG
        self.c = lxc.Container(self.CFG.container)
        assert(self.c.defined)
        self.logger = logging.getLogger("PyCon_StartStop")

    def get_cont(self):
        return self.c

    def run_command(self, command_str_list):
        """ Runs command with enviorment variables cleared """
        self.c.attach_wait(lxc.attach_run_command, command_str_list, env_policy=1)

    def __enter__(self):
        self.logger.info("Ensuring %s is running", self.CFG.container)
        with LockFile(self.CFG.COMMFILE) as lock:                            #pylint: disable=W0612
            # If not running, make it running
            if self.c.state == "STOPPED":
                self.c.start()
                # wait max 5 sec for container to run
                self.c.wait("RUNNING", 5)

            # Add my pid to container-users list
            try:
                with open(self.CFG.COMMFILE, 'r') as stream:
                    yaml_dict = yaml.safe_load(stream)
            except FileNotFoundError:
                # Obviously it's first run and we have to create state file
                self.logger.info("New state file for %s will be created", self.CFG.container)
                yaml_dict = {'Machine': [os.getpid(), ]}
            else:
                yaml_dict['Machine'].append(os.getpid())

            with open(self.CFG.COMMFILE, 'w') as outfile:
                outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )
        return self

    def __exit__(self, exception_type, value, traceback):
        with LockFile(self.CFG.COMMFILE) as lock:                            #pylint: disable=W0612
            with open(self.CFG.COMMFILE, 'r') as stream:
                yaml_dict = yaml.safe_load(stream)

            # Check if we are the last, so we should shutdown container
            my_pid = os.getpid()
            if len(yaml_dict['Machine']) == 1 and yaml_dict['Machine'][0] == my_pid:
                print("\nShutting down {0}...".format(self.CFG.container))
                if not self.c.shutdown(10):
                    self.c.stop()
                print(self.c.state)
            elif len(yaml_dict['Machine']) == 1:
                tmp_str = ("Container user list contains one pid ({0}), "
                           "which isn't mine ({1}).").format(yaml_dict['Machine'][0], my_pid)
                self.logger.error(tmp_str)
                raise RuntimeError(tmp_str)

            # Remove my pid from list and write
            yaml_dict['Machine'].remove(my_pid)
            with open(self.CFG.COMMFILE, 'w') as outfile:
                outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )


class Xpra(object):
    """
    Basic class implementing run_xpra/halt_xpra methods for starting/stopping
    in-container Xpra server. Requires container to be running.
    """
    def __init__(self, CFG):
        self.CFG = CFG
        self.c = lxc.Container(self.CFG.container)
        assert(self.c.defined)
        assert(self.c.state == "RUNNING")

    def run_xpra(self):
        run_command = ['sudo', '-u', self.CFG.in_container_username, 'xpra',
                       '--socket-dir=/home/{0}/xpra-socket/'.format(self.CFG.in_container_username),
                       'start', ':{0}'.format(self.CFG.display) ]
        self.c.attach_wait(lxc.attach_run_command, run_command, env_policy=1)

    def halt_xpra(self):
        halt_command = ['sudo', '-u', self.CFG.in_container_username, 'xpra',
                        '--socket-dir=/home/{0}/xpra-socket/'.format(self.CFG.in_container_username),
                        'stop', ':{0}'.format(self.CFG.display) ]
        self.c.attach_wait(lxc.attach_run_command, halt_command, env_policy=1)


@add_spawn_worker
class SSXpra(Xpra):
    """
    Xpra contex manager respecting container's YAML state file
    """
    def __init__(self, CFG):
        self.CFG = CFG
        self.c = lxc.Container(self.CFG.container)
        assert(self.c.defined)
        self.logger = logging.getLogger("PyCon_StartStopXpra")

    def __enter__(self):
        assert(self.c.state == "RUNNING")
        with LockFile(self.CFG.COMMFILE) as lock:                            #pylint: disable=W0612
            with open(self.CFG.COMMFILE, 'r') as stream:
                yaml_dict = yaml.safe_load(stream)

            if self.CFG.xpra not in yaml_dict or yaml_dict[self.CFG.xpra] == []:
                self.run_xpra()
                self.spawn_worker()
                yaml_dict[self.CFG.xpra] = [os.getpid(), ]
            else:
                yaml_dict[self.CFG.xpra].append(os.getpid())

            with open(self.CFG.COMMFILE, 'w') as outfile:
                outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )
        return self

    def __exit__(self, exception_type, value, traceback):
        # AtDeTach functionality somewhat depends on this method
        with LockFile(self.CFG.COMMFILE) as lock:                            #pylint: disable=W0612
            with open(self.CFG.COMMFILE, 'r') as stream:
                yaml_dict = yaml.safe_load(stream)

            my_pid = os.getpid()
            if len(yaml_dict[self.CFG.xpra]) == 1 and yaml_dict[self.CFG.xpra][0] == my_pid:
                self.halt_xpra()
                if yaml_dict[self.CFG.xpra_worker] == 'DISABLED':
                    yaml_dict[self.CFG.xpra_worker] = None

            elif len(yaml_dict[self.CFG.xpra]) == 1:
                tmp_str = ("Xpra user list for {0} contains one pid ({1}), "
                           "which isn't mine ({2}).").format(self.CFG.container,
                                                             yaml_dict[self.CFG.xpra][0],
                                                             my_pid)
                self.logger.error(tmp_str)
                raise RuntimeError(tmp_str)

            yaml_dict[self.CFG.xpra].remove(my_pid)
            with open(self.CFG.COMMFILE, 'w') as outfile:
                outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )


@add_spawn_worker
class AtDeTach(object):
    """ Allows attaching/detaching client to/from container xpra server."""
    def __init__(self, CFG):
        self.CFG = CFG
        self.logger = logging.getLogger("PyCon_AtDeTach")

    def _attach(self):
        self.logger.info('Attaching Xpra to container %s display %s...',
                         self.CFG.container, self.CFG.display)
        with open(self.CFG.COMMFILE, 'r') as stream:
            yaml_dict = yaml.safe_load(stream)

        if self.CFG.xpra_worker in yaml_dict and yaml_dict[self.CFG.xpra_worker] == 'DISABLED':
            yaml_dict[self.CFG.xpra_worker] = None
            with open(self.CFG.COMMFILE, 'w') as outfile:
                outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )
            self.spawn_worker()

        else:
            self.logger.warning(('Failed attaching Xpra to container %s display %s. '
                                 'Wroker wasn\'t started, wasn\'t detached or '
                                 'state file may be insane.'),
                                self.CFG.container,
                                self.CFG.display)

    def _detach(self):
        """
        Detach is realized by writing 'DISABLED' as xpra_worker in state file
        and requesting detach from xpra server. Then, worker exists on its own.
        """
        self.logger.info('Detaching Xpra from container %s display %s...',
                         self.CFG.container, self.CFG.display)
        xpra_detach = ['xpra',
                       '--socket-dir={0}/{1}/rootfs/home/{2}/xpra-socket/'.format(self.CFG.containers_catalog,
                                                                                  self.CFG.container,
                                                                                  self.CFG.in_container_username),
                       'detach', ':{0}'.format(self.CFG.display) ]

        with open(self.CFG.COMMFILE, 'r') as stream:
            yaml_dict = yaml.safe_load(stream)

        if self.CFG.xpra_worker in yaml_dict and isinstance(yaml_dict[self.CFG.xpra_worker], int):
            yaml_dict[self.CFG.xpra_worker] = 'DISABLED'
            with open(self.CFG.COMMFILE, 'w') as outfile:
                outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )
            subprocess.call(xpra_detach)

        else:
            self.logger.warning(('Failed detaching Xpra to container %s display %s. '
                                 'Wroker wasn\'t started, wasn\'t attached or '
                                 'state file may be insane.'),
                                self.CFG.container,
                                self.CFG.display)

    def _safer(self, action):
        Sane = InSanity(Config, logger=self.logger)
        if not Sane.check():
            raise RuntimeError("State file is Insane!")

        with LockFile(self.CFG.COMMFILE) as lock:                            #pylint: disable=W0612
            if action == 'detach':
                self._detach()
            elif action == 'attach':
                self._attach()

    def attach(self):
        self._safer('attach')

    def detach(self):
        self._safer('detach')



if __name__ == "__main__":
    pass
# Thats just how I roll
