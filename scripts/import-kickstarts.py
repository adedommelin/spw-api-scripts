#!/usr/bin/env python
# -*- coding: utf-8 -*-
# a script to import a kickstart file from a JSON dump file
# created by the companion kickstart2json script
# author Stuart Sears <sjs@redhat.com>
# this has only been slightly tested but appears to work
# as with all unsuppoted scripts, backup your satellite DB
# before running this, as it may have unforseen effects.

__doc__ = """
a script to import kickstart profiles from a JSON dump file
created by the companion export-kickstarts.py script
"""
__author__ = "Stuart Sears <sjs@redhat.com>"

import sys
import os
from optparse import OptionParser, OptionGroup
from pprint import pprint

# custom module imports (check they're on your pythonpath)
import rhnapi
from rhnapi import kickstart
from rhnapi import activationkey
from rhnapi import configchannel
from rhnapi import systemgroup
from rhnapi import utils


RHNHOST = 'localhost'
RHNCONFIG = '~/.rhninfo'
# put these in your configfile, dammit;
RHNUSER = None
RHNPASS = None

# for adding new profiles, we require a root password.
# This is overridden when we set the 'advanced options'
# so can be anything we want. 
TEMP_ROOT_PW = 'iwuebfwoeipfh'

# --------------------------------------------------------------------------------- #
def parse_cmdline(argv):
    """
    process the commandline :)
    """
    preamble = "Load and import kickstart profiles from a JSON-format text file (created by export-kickstarts.py)"
    usagestr = "%prog [OPTIONS]... JSONFILE"
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
    ksgrp = OptionGroup(parser, "Kickstart-specific options")
    ksgrp.add_option("--list", action="store_true", default=False, help="List kickstart labels in the specified file and exit")
    ksgrp.add_option("-k", "--kickstart", help="kickstart label to import from local file. Default: import ALL kickstarts in file")
    ksgrp.add_option("-n", "--not-really", action="store_true", default=False, help="DRY RUN. Pretty print data to stdout")
    ksgrp.add_option("-i", "--interactive", action="store_true", default=False, help="Ask whether to create missing elements [%default]")
    ksgrp.add_option("-p", "--pretty-print", dest = "printonly", action="store_true", default=False, help="Simply pretty-print the chosen kickstart object(s) [%default]")
    # disabled these two for the time being as the code hasn"t been written yet
    # ksgrp.add_option("-r", "--replace", action="store_true", default=False, help="replace kickstarts on satellite with those in file (only if names match) DANGEROUS.")
    # ksgrp.add_option("-R", "--rename", action="store_true", default=False, help="offer to rename imported kickstart profiles if there is a name clash.")
    parser.add_option_group(ksgrp)


    opts, args = parser.parse_args()
    # expect the JSON file as first argument
    if len(args) != 1:
        print "Insufficient information provided: no FILENAME"
        parser.print_help()
        sys.exit(1)

    elif not os.path.isfile(args[0]):
        print "file %s does not appear to exist." % args[0]
        sys.exit(2)
    # check the args for errors etc...

    ''# finally...
    return opts, args

# --------------------------------------------------------------------------------- #

def set_ks_details(rhn, ksobject, interactive = False,verbose = False):
    """
    Work through the dict structure representing a kickstart profile, setting the
    various elements on the server.
    This will also create missing items if you let it, specifically
    1. Activation Keys
    during the activation key creation process, we may also create the following,
    if they are missing from the local satellite, but used by the activation key:
        1. system groups (by name)
        2. GPG and/or SSL keys (by name)
    2. Pre and Post Scripts (recreated with content)
    3. File Preservation lists (by name)
    """
    #    ksobject['ks_tree']               = kickstart.getKickstartTree(rhn, kslabel)
    # assuming the object already exists, fetch the label for ease of typing:
    kslabel = ksobject.get('label')
    if verbose:
        print "processing kickstart label %s" % kslabel
    #    ksobject['child_channels']        = kickstart.getChildChannels(rhni, kslabel)
    if verbose:
        print "setting child channel subscriptions"
    if kickstart.setChildChannels(rhn, kslabel, ksobject['child_channels']):
        print "child channels set"
    #    ksobject['partitioning_scheme']   = kickstart.getPartitioningScheme(rhn, kslabel)
    if verbose:
        print "processing advanced options"
    if kickstart.setAdvancedOptions(rhn, kslabel, ksobject['advanced_opts']):
        print "advanced options successfully imported"

    if verbose:
        print "setting partitioning scheme"
    if kickstart.setPartitioningScheme(rhn, kslabel, ksobject['partitioning_scheme']):
        print "Partitioning scheme successfully imported."

    if verbose:
        print "setting software list"
    if kickstart.setSoftwareList(rhn, kslabel, ksobject['software_list']):
        print "software list added to kickstart"

    if verbose:
        print "setting custom kickstart options"
    if kickstart.setCustomOptions(rhn, kslabel, ksobject['custom_opts']):
        print "Custom Options successfully imported"

    if verbose:
        print "adding pre and post scripts"
    for script in ksobject['script_list']:
        res = kickstart.addScript(rhn, kslabel, script['contents'], script['script_type'], script['chroot'], script['interpreter'])
        if isinstance(res, int):
            print "added %s script number %d" % (script['script_type'], res)
        else:
            print "failed to add %s script, continuing anyway % script['type']"
            print res
            continue

    if verbose:
        "print importing IP ranges for bare-metal kickstart"
    for iprange in ksobject['ip_ranges']:
        if kickstart.addIpRange(rhn, kslabel, iprange['min'], iprange['max']):
            print "added ip range %s-%s" %(iprange['min'], iprange['max'])
        else:
            print "failed to add ip range %s-%s, continuing" %(iprange['min'], iprange['max'])
            continue

    if verbose:
        print "importing custom variable list"
    if kickstart.setVariables(rhn, kslabel, ksobject['variable_list']):
        print "sucessfully imported custom variables. Please check them for sanity"
    #    ksobject['reg_type']              = kickstart.getRegistrationType(rhn, kslabel)
    if verbose:
        print "setting post-build registration type"
    if kickstart.setRegistrationType(rhn, kslabel, ksobject['reg_type']):
        print "sucessfully set post-build registration to %s" % ksobject['reg_type']
    #    ksobject['file_preservations']    = kickstart.listFilePreservations(rhn, kslabel)
    if verbose:
        print "importing file preservations"
    if len(ksobject['file_preservations']) != 0:
        add_fpres = []
        for fpres in ksobject['file_preservations']:
            if fpres['name'] in existing_file_preservations:
                add_fpres.append(fpres['name'])
            else:
                if interactive:
                    res = utils.prompt_confirm('create missing file preservation list %s' % fpres['name']) 
                else:
                    res = True

                if res:
                    if kickstart.createFilePreservation(rhn, fpres['name'], fpres['file_names']):
                        print "file preservation created"
                        # add it to the global list for future use
                        existing_file_preservations.append(fpres['name'])
                        # add it to our list
                        add_fpres.append(fpres['name'])
                    else:
                        print "could not create missing file preservation list %s, skipping" % fpres['name']
                        continue
        # now we have a list of existing preservations to add, let's add them!
        for fp in add_fpres:
            if kickstart.addFilePreservations(rhn, kslabel, [ fp ]):
                print "added file preservation '%s'" % fp
            else:
                print "unable to add file preservation %s, skipping" % fp
                    

    if ksobject['config_mgmt']:
        if verbose:
            print "enabling configuration management"
        if kickstart.enableConfigManagement(rhn, kslabel):
            print "COnfiguration Management enabled"

    if ksobject['remote_cmds']:
        if verbose:
            print "enabling remote commands"
        if kickstart.enableRemoteCommands(rhn, kslabel):
            print "Remote Commands Enabled"
    #    ksobject['activation_keys']       = kickstart.getActivationKeys(rhn, kslabel)
    # run through the activation keys in our stored kickstart structure
    # 1. if they exist in the satellite, add them to the kickstart
    # 2. if they don't exist, try to create them in the satellite first
    # 3. else, FAIL and say so

    if verbose:
        print "processing activation keys"
    for akey in ksobject['activation_keys']:
        # assume existing keys with the correct 'name' and description are okay.
        if (akey['description'], akey['key']) in existing_act_keys:
            print "activation key '%s' (%s)  exists on your satellite, adding it to the kickstart" % (akey['description'], akey['key'])
            if kickstart.addActivationKey(rhn, kslabel, akey['key']):
                print "successfully added key %s" % akey['key']
        else:
            if interactive:
                res = utils.prompt_confirm("activation key '%s (%s)' does not appear to already exist. Create it" % (akey['description'], akey['key']))
            else:
                res = True
            if res:
                if create_activation_key(rhn, akey, interactive, verbose):
                    kickstart.addActivationKey(rhn, kslabel, akey['key'])
                else:
                    print "key %s does not exist and we couldn't create it. Skipping it."
                    continue

    #    ksobject['gpg_ssl_keys']          = kickstart.listKeys(rhn, kslabel)
    if verbose:
        print "processing GPG and SSL keys"
    # run through the crypto keys in our kickstart JSON structure and
    # 1. check if they already exist in satellite.
    # 2. if so, add them to our kickstart
    # 3. if not, try to create them first, then add them to the kickstart
    # 4. finall, FAIL and say so.

    for akey in ksobject['gpg_ssl_keys']:
        if akey['description'] in existing_crypto_keys:
            if kickstart.addCryptoKeys(rhn, kslabel, akey['description']):
                print 'added key "%s"' % akey['description']
        elif create_crypto_key(rhn, akey, interactive, verbose):
            print "created new stored cryptokey %s" % akey['description']
            if kickstart.addCryptoKeys(rhn, kslabel, akey['description']):
                print 'added key "%s"' % akey['description']
        else:
            if verbose:
                print "key %s does not exist and I couldn't create it. skipping..." % akey['description']
            continue

# --------------------------------------------------------------------------------- #

def create_activation_key(rhn, keyinfo, interactive = False, verbose = False):
    """
    creates an activation key so we can assign it to a kickstart
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
    mykey = keyinfo['key'].split('-')[1]

    # now try to create it. There is more than one way to do this, depending on
    # whether you specify a usage limit or not.
    if keyinfo['usage_limit'] != 0:
        keyid = activationkey.create(rhn,
                        mykey,
                        keyinfo['description'],
                        keyinfo['base_channel_label'],
                        keyinfo['entitlements'],
                        usagelimit = keyinfo['usage_limit'],
                        universalDefault = keyinfo['universal_default'])
    else:
        keyid = activationkey.create(rhn,
                        mykey,
                        keyinfo['description'],
                        keyinfo['base_channel_label'],
                        keyinfo['entitlements'],
                        universalDefault = keyinfo['universal_default'])
    if keyid != False:
        if verbose:
            print "key created" 

        # add the key to our global activation key list to avoid having to do this again

        existing_act_keys.append( (keyinfo['description'], keyid) )

        print "adding child channels to key %s" % keyid    
        if activationkey.addChildChannels(rhn, keyid, keyinfo['child_channel_labels']):
            print "child channels successfully added"
            
        print "adding packages"
        if activationkey.addPackages(rhn, keyid, keyinfo['packages']):
            print "packages added"

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
            if activationkey.addConfigChannels(rhn, [ keyid ] , configlabels):
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
                if grp['name'] in existing_system_groups:
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
                            existing_system_groups.append(newgrp['name'])
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

def create_crypto_key(rhn, keyinfo, interactive = False, verbose = False):
    """
    creates a new crypto key so we can add it to a kickstart
    """
    return kickstart.createCryptoKey(rhn, keyinfo['description'], keyinfo['type'], keyinfo['content'])

# --------------------------------------------------------------------------------- #

def remove_ks(rhn, kslabel):
    """
    For deleting kickstart profiles that already exist.
    NOT USED YET
    """
    return kickstart.deleteProfile(rhn, kslabel)

# --------------------------------------------------------------------------------- #

def create_ks(rhn, ksobject, verbose = False):
    """
    Create a new basic KS profile with the bare minimal info
    createProfile(rhn, ksLabel, ksTree, rootPass, ksHost='', vtType='none')
    """
    return kickstart.createProfile(RHN, ksobject['label'], ksobject['ks_tree'],TEMP_ROOT_PW)

# --------------------------------------------------------------------------------- #

def rename_ks(ksobject, newname, verbose = False):
    """
    renames a kickstart object we have loaded locally to avoid name clashes
    This sort-of assumes that the name is the same as the label. Oh, well.
    NOT USED YET
    """

    if verbose:
        print "renaming %s to %s" %(ksobject['label'], newname)

    ksobject['label'] = newname
    ksobject['name'] = newname
    
    return ksobject
    
# --------------------------------------------------------------------------------- #

if __name__ == '__main__':
    """
    This script is intended to do the following:
    1. load a list of kickstart structures from a JSON file (exported by its companion script, kickstart2json)
    2. create these profiles on the local satellite
    Steps required...
    * do the Activation Keys specified already exist?
    * do the GPG / SSL keys exist?
    - if not, create them
    * do the relevant kickstart trees / channels exist already?
    - if not, FAIL. (nicely)
    - is the org the same?
    * does the kickstart already exist?
    - support renaming or replacement.
    then...
    - create the profile
    - set the various detail elements
    - check it all works
    """
    
    opts, args = parse_cmdline(sys.argv)
    # initialiase an RHN Session
    # print "This is under heavy development and is currenttly non-functional"
    # sys.exit(0)
    try:
        # variables for existing server info
        global existing_act_keys
        global existing_crypto_keys
        global existing_system_groups
        global existing_file_preservations

        ## --- first, we work with the JSON file - we may not need to connect to RHN at all --- ##
        # there are a number of tasks we can perfom which only require the local JSON file:

        ksobjects = utils.loadJSON(args[0])

        local_labels = [ x.get('label') for x in ksobjects ]

        if opts.verbose:
            print "kickstart labels in file:"
            print '\n'.join(local_labels)

        # if --list, we just read the data and dump a list of labels:
        if opts.list:
            print '\n'.join( [ x['label'] for  x in ksobjects ])
            sys.exit(0)

        # populate import_list with kickstart details we wish to import
        import_list = []
        # firstly,
        # did we choose a kickstart profile (or list of them?)
        if opts.kickstart:
            import_list = [ x for x in ksobjects if x['label'] in opts.kickstart.split(',') ]
            if opts.verbose:
                print import_list
                
        else:
            import_list = ksobjects

        if opts.printonly:
            for ksitem in import_list:
                print '## ------------- Kickstart Details for %s ----------------- ##' % ksitem['label']
                pprint(ksitem)
                print
            sys.exit(0)


        # -- connect to RHN Satellite Server --- #
        if opts.verbose:
            print "Connecting to satellite server %s" % opts.server
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache, debug=opts.debug)
        if opts.debug:
            RHN.enableDebug()
        if opts.verbose:
            print "gathering information about existing elements..."
        # get a list of existing kickstart profiles
            print "1. Existing kickstarts...",
        # this doesn't need to be global, we're only using it here...
        all_kickstarts = kickstart.listKickstarts(RHN)
        if opts.verbose:
            print "done"
        # suck just the labels out as these have to be unique
        remote_labels = [ x.get('label') for x in all_kickstarts ]

        if opts.verbose:
            print "2. Existing activation keys (can take a long time)...",
        # make our list of activation keys accessible to all methods:
        existing_act_keys = activationkey.listActivationKeyNames(RHN)
        if opts.verbose:
            print "done"

        if opts.verbose:
            print "3. Existing Crypto (GPG and SSL) keys...",
        existing_crypto_keys = [ x['description'] for x in kickstart.listAllCryptoKeys(RHN) ]
        if opts.verbose:
            print "done."

        if opts.verbose:
            print "4. Existing system groups...",
        # we only care about the names...
        existing_system_groups = [ x['name'] for x in systemgroup.listAllGroups(RHN) ]
        if opts.verbose:
            print "done."

        if opts.verbose:
            print "5. Existing File Preservation Lists",
        # we only care about the names...
        existing_file_preservations = [ x['name'] for x in kickstart.listAllFilePreservations(RHN) ]
        if opts.verbose:
            print "done."

        # ----------------- Now work with the JSON file ------------------------ #

        # okay, did we provide a filename and does it exist?
        # if so, load it and read in the kickstart data:

        # now for the big job....
        for ksobject in import_list:
            if ksobject['label'] in remote_labels:
                print "kickstart label %s already exists, skipping" % ksobject['label']
                continue
            if create_ks(RHN, ksobject):
                set_ks_details(RHN, ksobject, opts.interactive, opts.verbose)
                
            else:
                print "unable to create kickstart %s" % ksobject['label']

        
    except KeyboardInterrupt:
        print "operation cancelled"
        sys.exit(1)


    
    
    
