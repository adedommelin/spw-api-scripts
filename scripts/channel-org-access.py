#!/usr/bin/env python
#
# A script to change/list channel org access
#
# Author : Steven Hardy <shardy@redhat.com>
# Based on clone-channel.py

"""
channel-org-access.py

a script to change/list channel org access

This requires the presence of the 'rhnapi' module on your PYTHONPATH.
"""

import sys
from optparse import OptionParser, OptionGroup
import logging
import re

# custom module imports
import rhnapi
from rhnapi import org
from rhnapi import channel
from rhnapi import utils
from datetime import time
import time

RHNHOST = 'localhost'
RHNCONFIG = '~/.rhninfo'
# put these in your configfile, dammit;
RHNUSER = None
RHNPASS = None

# --------------------------------------------------------------------------------- #
def parse_cmdline(argv):
    """
    process the commandline :)
    """
    preamble = "Change or list channel org access in your RHN Satellite. "
    usagestr = "%prog [OPTIONS] -c SOURCECHANNEL"
    # intitialise our parser instance and set some core options
    parser = OptionParser(usage = usagestr, description = preamble)
    parser.add_option("-V", "--debug", action = "store_true", default = False,
            help = "enable debug output for RHN session (XMLRPC errors etc")
    parser.add_option("-v", "--verbose", action = "store_true", default = False,
            help = "enable extra informational output")

    # RHN Satellite options group
    rhngrp = OptionGroup(parser, "RHN Satellite Options", "Defaults can be set in your RHN API config file (%s)" % RHNCONFIG )
    rhngrp.add_option("--server",help="RHN satellite server hostname [%default]", default=RHNHOST)
    rhngrp.add_option("--login", help="RHN login (username)" , default=RHNUSER)
    rhngrp.add_option("--pass", dest = "password", help="RHN password. This is better off in a config file.", default=RHNPASS)
    rhngrp.add_option("--config", dest = "config", help="Local RHN configuration file [ %default ]", default=RHNCONFIG)
    rhngrp.add_option("-C", "--cache", action = "store_true", default = False,
        help = "save usernames and password in config file, if missing")
    parser.add_option_group(rhngrp)

    changrp = OptionGroup(parser, "Channel Options")
    changrp.add_option("-c","--channel", dest = "channel", help = "channel LABEL", default=None)
    changrp.add_option("-o","--org", dest = "org", help = "org to enable/disable access", default=None)
    changrp.add_option("-l", "--list", help = "list channel org access then exit", action = "store_true", default=False)
    changrp.add_option("-d", "--disable", help = "disable org access", action = "store_true", default=False)
    changrp.add_option("-e", "--enable", help = "enable org access", action = "store_true", default=False)
    parser.add_option_group(changrp)


    opts, args = parser.parse_args()
    if opts.channel is None:
        print "no channel label provided"
        parser.print_help()
        sys.exit(1)

    if opts.disable is False and opts.enable is False and opts.list is False:
        print "must specify enable, disable or list"
        parser.print_help()
        sys.exit(1)

    return opts, args

if __name__ == '__main__':

    # Parse command line args and set loglevel
    opts, args = parse_cmdline(sys.argv)
    if opts.debug:
        print "Setting loglevel to DEBUG"
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)
        opts.verbose=True
        logging.debug("Debug level logging enabled")
    elif opts.verbose:
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)
    else:
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.WARNING)

    logging.debug("Got channel %s org %s" % (opts.channel, opts.org))

    try:
        # initialiase an RHN Session
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache, debug=opts.debug)
        if opts.debug:
            RHN.enableDebug()

        # Ensure the requested channel label exists
        channels = [ x['label'] for x in channel.listSoftwareChannels(RHN) ]
        if opts.channel not in channels:
            logging.error("source channel %s does not exist. Please try again" % opts.channel)
            logging.error("The following channels exist on your satellite:")
            logging.error('\n'.join(channels))
            sys.exit(1)

        # If they just asked for --list, we get channel org access and exit
        if opts.list:
            sharing = channel.getOrgSharing(RHN, opts.channel)
            print "Org sharing for channel %s is %s" % (opts.channel, sharing)
            # TODO : If protected then print per-org details
            sys.exit(0)

        # If a specific org was specified, this implies protected access
        if opts.org:
            # Ensure the requested org exists, and get the ID
            org_details = org.getDetails(RHN, opts.org)
            if org_details:
                logging.debug("Found requested org %s, ID is %d", (opts.org, org_details['id']))
            else:
                logging.error("Couldn't find org matching name %s!", opts.org)
                logging.error("The following orgs exist on your satellite:")
                orgs = org.listOrgs(RHN)
                orgnames = [ x['name'] for x in orgs ]
                print '\n'.join(orgnames)
                sys.exit(1)
            # Set the channel to protected access
            channel.setOrgSharing(RHN, opts.channel, 'protected')
            # Then enable/disable access for the specified org

        # However if they just specify a channel and --enable/--disable
        # this implies public/private access
        else:
            if opts.enable:
                channel.setOrgSharing(RHN, opts.channel, 'public')
            elif opts.disable:
                channel.setOrgSharing(RHN, opts.channel, 'private')
            else:
                logging.error("Unexpected error, channel specified with no enable/disable switch!")
                sys.exit(1)
            


    except KeyboardInterrupt:
        logging.debug("operation cancelled")
        sys.exit(1)

