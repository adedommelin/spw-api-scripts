#!/usr/bin/env python
# -*- coding: utf-8 -*-
# a script to clone a channel for when the web
# interface is inaccessible
"""
delete-channel.py

RHN XMLRPC API script to delete the chosen channel.

requires the rhnapi python module
"""
__author__ = "Stuart Sears <sjs@redhat.com>"

import sys
from optparse import OptionParser, OptionGroup

import rhnapi
from rhnapi import channel
from rhnapi import utils

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
    preamble = "Delete a channel (or list of channels) from your RHN Satellite. "
    usagestr = "%prog [RHNOPTS...] [-r|--list] CHANNEL..."
    # initialise our parser and set some default options
    parser = OptionParser(usage = usagestr, description = preamble)
    parser.add_option("--debug", action = "store_true", default = False,
            help = "enable debug output for RHN session (XMLRPC errors etc")
    parser.add_option('-v', '--verbose', action = 'store_true', default = False,
            help = "increase verbosity")

    # RHN Satellite options group
    rhngrp = OptionGroup(parser, "RHN Satellite Options", "Defaults can be set in your RHN API config file (%s)" % RHNCONFIG )
    rhngrp.add_option("--server",help="RHN satellite server hostname [%default]", default=RHNHOST)
    rhngrp.add_option("--login", help="RHN login (username)" , default=RHNUSER)
    rhngrp.add_option("--pass", dest = "password", help="RHN password. This is better off in a config file.", default=RHNPASS)
    rhngrp.add_option("--config", dest = "config", help="Local RHN configuration file [ %default ]", default=RHNCONFIG)
    rhngrp.add_option("--cache", action = "store_true", default = False,
        help = "save usernames and password in config file, if missing")
    parser.add_option_group(rhngrp)

    # script-specific options
    changrp = OptionGroup(parser, "Channel Options")
    changrp.add_option("-r", "--recursive", help = "delete channel(s) recursively, removing all children (dangerous)", action = "store_true", default=False)
    changrp.add_option("--list", action = "store_true", default = False,
            help = "just list custom channels (you can't delete any others) and exit")
    parser.add_option_group(changrp)

    opts, args = parser.parse_args()
    if len(args) == 0 and not opts.list:
        print "ERROR"
        print "You must provide at least one channel LABEL to delete"
        parser.print_help()
        sys.exit(1)
    if len(args) > 1 and opts.recursive:
        print "ERROR"
        print "For safety, --recursive only works on one base channel at a time"
        parser.print_help()
        sys.exit(1)
    # check the args for errors etc...

    # finally...
    return opts, args

# --------------------------------------------------------------------------------- #


if __name__ == '__main__':
    
    opts, chanlist = parse_cmdline(sys.argv)
    try:
        # login to our satellite
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache)
        # did we give the --debug switch?
        if opts.debug:
            RHN.enableDebug()

        if opts.list:
            print "Custom Software Channels"
            print "========================"
            mychans = [ x['label'] for x in channel.listMyChannels(RHN) ]
            for chan in mychans:
                print chan
                if channel.hasChildren(RHN, chan):
                    for child in channel.listChildren(RHN, chan):
                        print '  %(label)s'  % child
            sys.exit(0)


        # get a list of existing channels
        existing_channels = [ x['label'] for x in channel.listSoftwareChannels(RHN) ]

        for chan in chanlist:
            if chan not in existing_channels:
                print "channel label %s does not exist. Skipping it." % chan
                continue

            if channel.hasChildren(chan):
                child_chans = channel.listChildChannels(RHN, chan)
                if opts.recursive:
                    for child in child_chans:
                        if opts.verbose:
                            print "deleting child channel %s" % child
                        if channel.delete(RHN, child):
                           print "deleted child channel %s" % child
                else:
                    print 'channel %s has child channels. please delete them first or use the -r/--recursive option' % chan
                    print 'children:'
                    print '\n'.join( child_chans)
                    sys.exit(2)
            
            if channel.delete(RHN, chan):
                print "deleted channel %s" % chan

    except KeyboardInterrupt:
        print "operation cancelled"
        sys.exit(1)


    
    
    
