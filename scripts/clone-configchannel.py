#!/usr/bin/env python
# -*- coding: utf-8 -*-
# json2configchannel.py
# A script to create config channels on an RHN satellite from JSON dumps
# author: Stuart Sears <sjs@redhat.com>
# This script may or may not do unpleasant things to your satellite.
# make backups first.

__doc__ = """
clone-configchannel.py

A script to create a cloned set of configuration channels on a satellite from a JSON dump.
it will
* gather information about your chosen configuration channel
* create a new, empty configchannel with the chosen name
* create and populate files, directories and symlinks, based on the old channel content

In doing this you lose version history on the files in the new channel - only the latest revision is imported.
"""
__author__ = "Stuart Sears <sjs@redhat.com>"

# standard library imports
import sys
import os
import time
from optparse import OptionParser, OptionGroup

# custom modules. Make sure they're on your PYTHONPATH
# hint:
# sys.path.append('parent directory of rhnapi')

import rhnapi
from rhnapi import configchannel
from rhnapi import utils

# global vars for defaults
# At least RHNHOST *must* be specified.
RHNHOST = 'localhost'
RHNCONFIG = '~/.rhninfo'
# put these in your configfile, dammit;
RHNUSER = None
RHNPASS = None
        
# --------------------------------------------------------------------------------- #

def parse_cmdline(argv):
    """
    process the commandline :)
    give this sys.argv[1:] as an argument to avoid any issues with the script name
    being considered an 'argument' and processed
    """
    preamble = "Clone a configuration channel (to form part of a release or promotion within workflow)"
    usagestr = "%prog [OPTIONS] SOURCECHANNEL DESTCHANNEL"
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
    ccgrp = OptionGroup(parser, "Configuration Channel Options")
    ccgrp.add_option("-c","--channel",
        help="Channel to create/import from JSON file. Default is ALL channels")
    ccgrp.add_option("--list", action="store_true", default=False,
        help="just list config channel labels in the JSON file and exit")
    ccgrp.add_option("-u","--update", action="store_true", default = False,
        help="Update existing channels, rather than skipping them. Use with caution.")
    ccgrp.add_option("-r","--replace", action="store_true", default = False,
        help="Replace (delete and recreate) existing channels, rather than skipping them. Use with caution.")

    parser.add_option_group(ccgrp)
    # add debug option for xmlrpc errors

    opts, args = parser.parse_args(argv)
    # so sanity-chacking stuff here
    if len(args) != 2 and not opts.list: 
        print "we require both source and destination channel labels"
        parser.print_help()
        sys.exit(1)

    # finally return the cleaned options and args
    return opts, args
        
# --------------------------------------------------------------------------------- #

def get_confchannel_info(rhn, channel_label, verbose=False):
    """
    Processes the specified channels, getting filelists and metadata
    """
    channeldata = configchannel.detailsByLabel(rhn, channel_label)
    filelist = [ x['path'] for x in configchannel.listFiles(rhn, channel_label) ]
    channeldata['files'] = []
    for fentry in configchannel.lookupFileInfo(rhn, channel_label, filelist):
        if verbose:
            print "processing file %s" % fentry['path']
        channeldata['files'].append(fentry)
    return channeldata
        
# --------------------------------------------------------------------------------- #

def create_config_channel(rhn, chanobj, verbose=False):
    """
    The actual channel creation
    """
    chandata = configchannel.create(rhn, chanobj['label'], chanobj['name'], chanobj['description'])
    if chandata is not False:
        existing_labels.append(chandata['label'])
        return True
        
# --------------------------------------------------------------------------------- #

def add_channel_content(rhn, chanobj, verbose=False):
    """
    Adds a file, directory or symlink to the given configuration channel.
    if the object already exists, it will be replaced and its revision number updated.

    returns: True or False

    parameters:
    rhn(rhnapi.rhnSession)      - authenticated RHN session
    chanobj(dict)               - channel object imported from JSON
    fileobj(dict)               - file/dir/symlink object
    verbose(bool)               - be more verbose [False]
    """
    fail_list = []
    for fobj in chanobj['files']:
        objtype = fobj.get('type', 'file')
        objpath = fobj.get('path', 'None')
        if verbose:
            print "adding file %s to config channel" % fobj['path']
        if configchannel.createOrUpdateObject(rhn, chanobj['label'], fobj):
            if verbose:
                print "Added %s %s to channel %s" %(objtype, objpath, chanobj['label'])
        else:
            if verbose:
                print "Failed to add %s %s to channel %s " %(objtype, objpath , chanobj['label'])
            fail_list.append(fobj)
            continue

    # if we have anything in the fail_list, make sure we pass it back to caller
    if len(fail_list) != 0:
        return fail_list
    # else, it must have all worked.
    else:
        return None
        
# --------------------------------------------------------------------------------- #

def update_channel_content(rhn, chanobj, verbose=False):
    """
    simply removes the 'revision' numbers from the file objects, then passes them onto
    'add_channel_content' to use...
    """
    for fobj in chanobj['files']:
        if fobj.has_key('revision'):
            del fobj['revision']

    return add_channel_content(rhn, chanobj, verbose=False)
        
# --------------------------------------------------------------------------------- #

if __name__ == '__main__':
    
    # process command-line arguments
    opts, args = parse_cmdline(sys.argv[1:])
    
    # declare this as global as we'll be modifying it in a number of places as we
    # import config channels
    global existing_labels

    try:
        # connect to RHN:
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache)
        if opts.debug:
            RHN.enableDebug()
        # get a list of all existing channels - allows us to check for existing channels.
        existing_labels = [ x['label'] for x in configchannel.listGlobals(RHN) ]

        # if we asked for a list, just do that and exit
        if opts.list:
            print "Existing Configuration Channels:"
            print '\n'.join(existing_labels)
            sys.exit(0)

        else:
            sourcechannel, destchannel = args
# --------------------------------------------------------------------------------- #

        if sourcechannel not in existing_labels:
            print "Source channel label %s does not appear to exist on your satellite." % sourcechannel
            sys.exit(2)
        else:
            # fetch the existing source channel data:
            chandata = get_confchannel_info(RHN, sourcechannel, opts.verbose)
            # make changes to reflect the destination channel info (with a timestamp)
            chandata.update({ 'name' : destchannel,
                'label' : destchannel,
                'description' : '%s [Cloned on %s]' % (chandata['description'], time.strftime('%Y-%m-%d %H:%M')) })

        if opts.verbose:
            print "Starting cloning process for Config Channel %s" % sourcechannel
        if destchannel in existing_labels:
            # okay, the channel already exists, do we want to replace it?
            if opts.replace:
                print "replacing already existing channel %s" % destchannel
                # let's keep a backup of the existing data instead
                res = configchannel.deleteConfigChannel(RHN, chandata['label']) and create_config_channel(RHN, chandata , opts.verbose)
                if not res:
                    print "failed to replace existing channel %s" % chandata['label']

            # channel exists, we want to update in-place...
            elif opts.update:
                print "Channel %s already exists, updating the files in it" % chandata['label']
            # channel exists and we are going to leave it alone...
            else:
                print "Channel %s already exists, skipping" % chandata['label']
                sys.exit(1)

        else:
            if create_config_channel(RHN, chandata):
                if opts.verbose:
                    print "created config channel %s" % chandata['label']
            else:
                print "could not create configuration channel %s, skipping it" % chandata['label']
                sys.exit(3)

            # now if we get here, our channel should exist...
            if opts.update:
                failed_objects = update_channel_content(RHN, chandata, opts.verbose)
            else:
                failed_objects = add_channel_content(RHN, chandata, opts.verbose)

            # process our failed objects, if there are any
            if failed_objects is not None:
                rejectsfile = "%s-rejects.json" %(chandata['label'])
                if opts.verbose:
                    print "some content could not be uploaded to %s" % chandata['label']
                    print "saving rejects to %s" % rejectsfile
                if utils.dumpJSON(failed_objects, rejectsfile):
                    print "Rejects saved to %s" % rejectsfile
                else:
                    print "could not save rejects file. This should not happen."
                    sys.exit(4)

    except KeyboardInterrupt:
        print "Operation Cancelled\n"
        sys.exit(1)



    

