#!/usr/bin/env python3
"""
This is the module docstring.

Status:
 - To Do
"""

import sys
import logging
import argparse

from pylc import Config, InSanity, StartStop, Xpra, SSXpra, AtDeTach



class CliParser(argparse.ArgumentParser):
    def set_default_subparser(self, name, args=None):
        """
        Slightly modified, from:
        http://stackoverflow.com/a/26378414
        https://bitbucket.org/ruamel/std.argparse/src/711eadeb3600e1ad0009b534802f8b91f4d56628/__init__.py?at=default
        https://github.com/epinna/weevely3/blob/master/core/argparsers.py

        default subparser selection. Call after setup, just before parse_args()
        name: is the name of the subparser to call by default
        args: if set is the argument list handed to parse_args()

        , tested with 2.7, 3.2, 3.3, 3.4
        it works with 2.6 assuming argparse is installed
        """
        subparser_found = False
        for arg in sys.argv[1:]:
            if arg in ['-h', '--help']:  # global help if no subparser
                break
            elif arg in ['launch', 'check', 'attach', 'detach', 'restart']:   # My Mod
                break
        else:
            for x in self._subparsers._actions:
                if not isinstance(x, argparse._SubParsersAction):
                    continue
                for sp_name in x._name_parser_map.keys():
                    if sp_name in sys.argv[1:]:
                        subparser_found = True
            if not subparser_found:
                # insert default in first position, this implies no
                # global options without a sub_parsers specified
                if args is None:
                    sys.argv.insert(1, name)
                else:
                    args.insert(0, name)



def launch_command():
    if Config.display is None:
        Config.display = 202
        Config.set_derived_parameters()

    if Config.command == []:
        Config.command = ['bash', ]

    Config.command = ['env', 'DISPLAY=:{0}'.format(Config.display),
                      'TERM=xterm-256color', ] + Config.command

    if not Config.root:
        Config.command = ['sudo', '-u', Config.in_container_username,
                          '-i', ] + Config.command

    Sane = InSanity(Config, logger=logging.getLogger(__name__))
    if not Sane.check():
        raise RuntimeError("State file is Insane!")

    with StartStop(Config) as SS:
        with SSXpra(Config) as SSX:
            SS.run_command(Config.command)

def check_insanity():
    S = InSanity(Config)
    S.check()

def attach_xpra():
    adt = AtDeTach(Config)
    adt.attach()

def detach_xpra():
    adt = AtDeTach(Config)
    adt.detach()

def restart_xpra_server():
    X = Xpra(Config)
    X.halt_xpra()
    X.run_xpra()

def no_xpra():
    if Config.command == []:
        Config.command = ['bash', ]

    Config.command = ['env', 'TERM=xterm-256color', ] + Config.command

    if not Config.root:
        Config.command = ['sudo', '-u', Config.in_container_username,
                          '-i', ] + Config.command

    Sane = InSanity(Config, logger=logging.getLogger(__name__))
    if not Sane.check():
        raise RuntimeError("State file is Insane!")

    with StartStop(Config) as SS:
            SS.run_command(Config.command)



if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    parser = CliParser(prog='pylc',
                       description="pylc - provides low friction LXC-Xpra-GUI command launching")
    subparsers = parser.add_subparsers()

    launch = subparsers.add_parser('launch', help="Launch a command. Default action")
    launch.set_defaults(func=launch_command)
    launch.add_argument('container', help="LXC container name")
    launch.add_argument('display', help="In-container Xpra display number", nargs='?', type=int)
    launch.add_argument('command', help="Command to be executed", nargs='*')
    launch.add_argument('--root', '-r', help="Run command as root", action='store_true')

    check = subparsers.add_parser('check', help="Check container YAML file")
    check.set_defaults(func=check_insanity)
    check.add_argument('container', help="LXC container name")

    attach = subparsers.add_parser('attach', help="Attach Xpra session to container")
    attach.set_defaults(func=attach_xpra)
    attach.add_argument('container', help="LXC container name")
    attach.add_argument('display', help="In-container Xpra display number", type=int)

    detach = subparsers.add_parser('detach', help="Detach Xpra session from container")
    detach.set_defaults(func=detach_xpra)
    detach.add_argument('container', help="LXC container name")
    detach.add_argument('display', help="In-container Xpra display number", type=int)

    restart = subparsers.add_parser('restart', help="Restart Xpra server in container")
    restart.set_defaults(func=restart_xpra_server)
    restart.add_argument('container', help="LXC container name")
    restart.add_argument('display', help="In-container Xpra display number", type=int)

    cli = subparsers.add_parser('cli', help="Launch a command - pure cli (no xpra)")
    cli.set_defaults(func=no_xpra)
    cli.add_argument('container', help="LXC container name")
    cli.add_argument('command', help="Command to be executed", nargs='*')
    cli.add_argument('--root', '-r', help="Run command as root", action='store_true')

    parser.set_default_subparser('launch')

    # args are written to Config namespace, so effectively Config == args
    Config = parser.parse_args(namespace=Config)
    Config.set_derived_parameters()
    Config.func()
