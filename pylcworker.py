#!/usr/bin/env python3
"""
This is the module docstring.

Status:
 - To Do
"""

import os
import time
import logging
import argparse
import subprocess

import lxc
import yaml
from lockfile import LockFile
from pylc import InSanity, Config



class ACL_Worker(Config):
    """
    Pseudo-daemon class, meant to be spawned from AtDeTach in pylc.py
    """
    def __init__(self):
        self.CONTAINER = lxc.Container(self.container)
        assert(self.CONTAINER.defined)
        self.logger = logging.getLogger("D{0}".format(self.display))
        self.Sane = InSanity(Config, logger=self.logger)
        self.xpra_connect = ['xpra',
                             '--socket-dir={0}/{1}/rootfs/home/{2}/.xpra/'.format(self.containers_catalog,
                                                                                        self.container,
                                                                                        self.in_container_username),
                             'attach', ':{0}'.format(self.display), ]
        self.setfacl = ['setfacl', '-m', 'u:1001:rw',
                        '/home/{0}/.xpra/{1}-{2}'.format(self.in_container_username,
                                                               self.hostname,
                                                               self.display), ]

    def run(self):
        self.logger.info("ACL Worker spawned for %s.", self.xpra_worker)
        self.logger.debug(Config)

        while True:
            self.Sane.check()
            with LockFile(self.COMMFILE) as lock:                            #pylint: disable=W0612
                with open(self.COMMFILE, 'r') as stream:
                    yaml_dict = yaml.safe_load(stream)

                if self.xpra in yaml_dict and len(yaml_dict[self.xpra]) > 0:
                    if self.xpra_worker not in yaml_dict or yaml_dict[self.xpra_worker] is None:
                        # Nominal case
                        yaml_dict[self.xpra_worker] = os.getpid()
                        self.logger.info("Setting my pid (%s) as %s.",
                                         yaml_dict[self.xpra_worker],
                                         self.xpra_worker)
                        with open(self.COMMFILE, 'w') as outfile:
                            outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )

                    elif yaml_dict[self.xpra_worker] == 'DISABLED':
                        self.logger.info("Worker disabled in state file.")
                        break

                    elif yaml_dict[self.xpra_worker] != os.getpid():
                        self.logger.warning("Pid %s already declared as %s, exiting",
                                            yaml_dict[self.xpra_worker],
                                            self.xpra_worker)
                        break

                else:
                    if self.xpra_worker in yaml_dict and yaml_dict[self.xpra_worker] == os.getpid():
                        self.logger.info(("Looks like container is shutting down "
                                          "(Xpra-%s users list is empty but I'm still its worker)"),
                                         self.display)
                        # Delete my pid from staus file, write and exit
                        yaml_dict[self.xpra_worker] = None
                        with open(self.COMMFILE, 'w') as outfile:
                            outfile.write( yaml.dump(yaml_dict, default_flow_style=False) )
                        self.logger.info("Exiting.")

                    else:
                        self.logger.warning(("Xpra-%s has no users on the list while "
                                             "starting worker. Exiting."),
                                            self.display)
                    break
            # Still in while, but not in lock - chanege ACL's and launch Xpra:
            self.CONTAINER.attach_wait(lxc.attach_run_command, self.setfacl, env_policy=1)
            # subprocess.call actually launches command and hangs until the command exits
            #xpra_exit_status = subprocess.call(xpra_connect)
            subprocess.call(self.xpra_connect)
            self.logger.debug("Xpra process of %s has exited", self.xpra_worker)
            time.sleep(1.5)
        # 'break' statement's above gets interpreter here
        return 0



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pseudo-Daemon for dispathing Xpra and controlling ACL's")
    parser.add_argument('container', help="LXC container name")
    parser.add_argument('display', help="In-container Xpra display number")
    Config = parser.parse_args(namespace=Config)
    Config.set_derived_parameters()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s %(levelname)s - %(message)s',
                        filename='{0}/worker-{1}.log'.format(Config.log_files_catalog,
                                                             Config.container), )

    aclw = ACL_Worker()
    aclw.run()
