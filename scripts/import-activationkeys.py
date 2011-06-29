#!/usr/bin/env python
# -*- coding: utf-8 -*-
# a script to dump a kickstart profile to JSON
__doc__ = """
A script to import activation keys from a JSON format textfile into your RHN Satellite.
The json file should have been created by the export-activationkeys.py script
tested on satellite 5.4, but still considered beta. Backup your satellite DB before using it.

What it attempts to import:
* activation keys
* system groups (by ID and name)
* config channels
* software channels

These items should exist on the destination satellite before you attempt to import a key that uses them.

This script uses the python 'rhnapi' module, which should be on your PYTHONPATH.
"""

__author__ = "Stuart Sears <sjs@redhat.com>"

# standard library imports
import sys
import os
from optparse import OptionParser, OptionGroup
from pprint import pprint
# for timestamps in filenames
import time
import re

# custom module imports. Make sure they're on your PYTHONPATH :)
import rhnapi
# software channel management
from rhnapi import channel
# config channel management
from rhnapi import configchannel
# activation key management
from rhnapi import activationkey
# this needs editing to add the ID->name functionality:
from rhnapi import systemgroup
# utility functions, including JSON management
from rhnapi import utils

RHNHOST = 'localhost'
RHNCONFIG = '~/.rhninfo'
# put these in your configfile, dammit;
RHNUSER = None
RHNPASS = None

# if we want to exclude reactivation keys (we probably do), this is a simple
# regex pattern that matches their descriptions.
react_pattern = re.compile(r'^(Kickstart )?(Reactivation|re-activation) Key.*$', re.I)

# --------------------------------------------------------------------------------- #
def parse_cmdline(argv):
    """
    process the commandline :)
    """
    preamble = "import all (or a list of) activation keys from a JSON-format text file"
    usagestr = "%prog [RHNOPTS] [OTHEROPTS] JSONFILE"
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
    keygrp = OptionGroup(parser, "Activation Key options", "Options for processing Activation Keys")
    keygrp.add_option("--list", action = "store_true", default = False, help = "List activation keys in file and exit [%default]")
    keygrp.add_option("-k", "--key", help = "Activation Key (the hyphenated 'hex string'). Can also take a comma-separated list. No spaces. If not specified, an attempt will be made to import all keys from your JSON file that do not currently exist on the satellite.")
    keygrp.add_option("-r", "--reactivation-keys", action = "store_true", default = False, help = "Import reactivation keys as well [%default]")
    keygrp.add_option("-n", "--not-really", action = "store_true", default = False, help = "DRY RUN. Simply report what would happen.")
    keygrp.add_option("-i", "--interactive", action = "store_true", default = False, help = "Operate in interactive mode. Can be very tedious.")
    parser.add_option_group(keygrp)


    opts, args = parser.parse_args()
    if len(args) != 1:
        print "you need to provide me a JSON file with activation key data in it"
        parser.print_help()
        sys.exit(1)
    elif not os.path.isfile(args[0]):
        print "%s does not appear to be a file."
        parser.print_help()
        sys.exit(1)
    # finally...
    return opts, args


# --------------------------------------------------------------------------------- #

def create_activation_key(rhn, keyinfo, interactive = False, verbose = False):
    """
    creates an activation key from a dict structure.
    This is complex... we have to
    1. create the key
    2. add base and child software channels
       - if they don't already exist with teh correct labels,
         this will fail :)
    4. set config management options and channels
       - missing config channels are skipped
    5. set group memberships
       - missing groups are created by name
    """
    if verbose:
        print "creating activation key '%s' (%s)" %(keyinfo['description'], keyinfo['key'])
        rhn.enableDebug()
    # remove the org prefix from the key (the satellite will add this for us)
    mykey = keyinfo['key'].split('-',1)[1]

    # now try to create it. There is more than one way to do this, depending on
    # whether you specify a usage limit or not.
    keyid = activationkey.create(rhn, keyinfo['description'], mykey, basechannel=keyinfo['base_channel_label'])
    
    if keyid != False:
        if verbose:
            print "key created" 


        if len(keyinfo['entitlements']) > 0:
            if verbose:
                print "adding entitlements '%s' to key" %(','.join(keyinfo['entitlements']))
            if activationkey.addEntitlements(RHN,keyid, keyinfo['entitlements']):
                print "Entitlements set appropriately"

        # add the key to our global activation key list to avoid having to do this again

        existing_keys.append( (keyinfo['description'], keyid) )

        if len(keyinfo['child_channel_labels']) > 0:
            print "Adding child channels"
            if activationkey.addChildChannels(rhn, keyid, keyinfo['child_channel_labels']):
                print "child channels successfully added"
            
        if len (keyinfo['packages']) > 0:
            print "Adding packages"
            for pkg in keyinfo['packages']:
                if activationkey.addPackages(rhn, keyid, [ pkg ]):
                    print "  - %s %s" %(pkg.get('name'), pkg.get('arch', '') )

        # add configuration channels to the key (if they exist)

        print "adding configuration channels to activation key (only if they exist)"
        configlabels = []

        # check that the config channels exist
        for chan in keyinfo['config_channels']:
            if configchannel.channelExists(rhn,chan['label']):
                configlabels.append(chan['label'])
            else:
                print "config channel label %s does not exist locally, skipping it."
                continue
        if len(configlabels) != 0:        
            if activationkey.addConfigChannels(rhn, [ keyid ], configlabels):
                print "added configuration channels to key"

        # process the config deployment checkbox (value = 1/0)
        if keyinfo['config_deploy'] == 1:
            res = activationkey.enableConfigDeployment(rhn, keyid)
        else:
            res = activationkey.disableConfigDeployment(rhn, keyid)
        if res:
            print "set configuration management deployment"
        if verbose:
            print "processing system group memberships"
        if keyinfo.has_key('server_groups'):
            add_groups = []
            for grp in keyinfo['server_groups']:
                if grp['name'] in existing_groups:
                    add_groups.append(grp)
                else:
                    # are we in interactive mode? This is passed all the way own from our commandline options
                    if interactive:
                        res = utils.prompt_confirm('create missing system group %s (%s)' % (grp['name'], grp['description']))
                    else:
                        res = True
                   
                    if res:
                        newgrp = create_group(rhn, grp)
                        if newgrp is not None:
                            print "group created"
                            existing_groups.append(newgrp['name'])
                            add_groups.append(newgrp)
                        else:
                            print "could not create group %s, skipping" % grp
                            continue
            for grp in add_groups:
                if verbose:
                    print "Adding existing system groups to key"
                if activationkey.addGroupsByName(rhn, keyid, grp['name']):
                    print "added group %s" % grp['name']
        return True
    else:
        return False

# --------------------------------------------------------------------------------- #

def create_group(rhn, groupinfo):
    """
    creates a system group (by name & description) if it doesn't already exist
    """
    groupdata =  systemgroup.create(rhn, groupinfo['name'], groupinfo['description']) 
    if groupdata is not None and groupdata is not False:
        return groupdata

    else:
        return None

# --------------------------------------------------------------------------------- #

def keytable(keylist):
    """
    Print a table of the description/key pairs in keytable
    """
    if len(keylist) == 0:
        print "(No Activation Keys found)"
        return False
    print "%-36s %s" %("Activation Key", "Description")
    print "-----------------------------------  ------------------------------------"
    for keyobj in keylist:
        print "%(key)-36s %(description)s" % keyobj

    
# --------------------------------------------------------------------------------- #

if __name__ == '__main__':
    """
    This script is intended to do the following:
    1. load a list of activation key structures from a JSON file
    2. check each key for missinig items on the satellite server.
    """
    opts, args = parse_cmdline(sys.argv[1:])
    jsonfile = args[0]
    verbose = opts.verbose

    try:
        # first let's attempt to load from the provided filename
        # no point in trying RHN connections if this fails

        keyobjects = utils.loadJSON(jsonfile)

        if not opts.reactivation_keys:
            keyobjects = [ x for x in keyobjects if not react_pattern.match(x['description']) ]
        # extract keynames - we'll use this to check if the key already exists.
        keynames = [ x['key'] for x in keyobjects ]
        if opts.key:
            selected_keys = [ x for x in keyobjects if x['key'] in opts.key.split(',') ]
        else:
            # well, if we didn't choose a key, then try to import all of them
            selected_keys = keyobjects

        if opts.list:
            print "Activation Keys in file %s" % jsonfile
            keytable(keyobjects)
            sys.exit(0)

        # global placeholders - we'll be passing these around and manipulating them
        global existing_keys
        global existing_groups
        global existing_channels
        global existing_configchannels

        # now we populate them
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache, debug = opts.debug)
        if verbose: print "Enumerating existing keys"
        # this is a list of tuples - ( description, key )
        existing_keys = activationkey.listActivationKeyNames(RHN)

        if verbose: print "Enumerating existing System Groups"
        existing_groups = [ x['name'] for x in systemgroup.listAllGroups(RHN) ]

        if verbose: print "Enumerating existing software channels"
        existing_channels = [ x['label'] for x in channel.listAllChannels(RHN) ]

        # handle debugging requests

        for keyobj in selected_keys:
            if (keyobj['description'], keyobj['key']) in existing_keys:
                print "Skipping Existing Activation Key '%(key)s'" % keyobj
                continue
            else:
                if opts.not_really:
                    print "Would import key %(key)s [%(description)s]" % keyobj
                    continue

                if create_activation_key(RHN, keyobj, opts.interactive, opts.verbose):
                    print "successfully imported activationkey %(key)s" % keyobj
                else:
                    print "Failed to import activationkey %(key)s, trying the next one" % keyobj
                    continue

                

        
    except KeyboardInterrupt:
        print "Operation cancelled by keystroke."
        sys.exit(1)
