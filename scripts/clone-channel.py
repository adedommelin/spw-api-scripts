#!/usr/bin/env python
# a script to clone a channel
# Can automate clone channel creation, including recursive cloning of base
# channels and their children

"""
clone-channel.py

A script to clone a channel in your RHN Satellite, with or without errata.

This requires the presence of the 'rhnapi' module on your PYTHONPATH.
"""

import sys
from optparse import OptionParser, OptionGroup
import logging
import re

# custom module imports
import rhnapi
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
    preamble = "Clone a channel in your RHN Satellite. "
    usagestr = "%prog [OPTIONS] [-p PARENT] -c SOURCECHANNEL -d DESTCHANNEL"
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
    changrp.add_option("-c","--source-channel", dest = "source", help = "source channel LABEL", default=None)
    changrp.add_option("-r", "--child", help = "clone recursively, e.g a channel and all it's children", action = "store_true", default=False)
    changrp.add_option("-d","--dest-channel", dest = "dest", help = "destination channel LABEL, note this is used as a prefix to existing labels when cloning recursively using -r/--child", default=None)
    changrp.add_option("-n","--no-errata", help="do not clone errata [%default]", action="store_true", default=False)
    changrp.add_option("-p","--parent", help="parent for new channel. Your new channel will be a base channel without this.", default=None)
    changrp.add_option("-s","--summary", help="Channel Summary - dest label used if omitted.", default=None)
    changrp.add_option("-i", "--interactive", help = "run in interactive mode [%default]", action = "store_true", default=False)
    changrp.add_option("-x","--regex", dest = "regex", help = "sed-syntax regex to formulate the destination channel labels by doing a regex replacement on source channel label(s), useful for --child clones where no prefix is desired", default=None)
    parser.add_option_group(changrp)


    opts, args = parser.parse_args()
    if opts.source is None:
        print "no source channel label provided"
        if opts.interactive:
            opts.source = utils.prompt_missing('source channel LABEL: ')
        else:
            parser.print_help()
            sys.exit(1)
    
    if opts.dest is None and opts.regex is None:
        print "no destination channel label or regex provided"
        if opts.interactive:
            opts.dest = utils.prompt_missing('destination channel LABEL: ')
        else:
            parser.print_help()
            sys.exit(1)

    return opts, args

# --------------------------------------------------------------------------------- #
def user_ask_ok(prompt):
    retries=4
    while True:
        ok = str(raw_input(prompt)).lower()
        if ok in ('y', 'yes'):
            return True
        if ok in ('n', 'no'):
            return False
        retries = retries - 1
        if retries < 0:
            raise IOError('refused by user')
        print "Please enter yes/y or n/no"

# --------------------------------------------------------------------------------- #

def label_to_name(label):
    """
    perform some basic substitutions on a string to make it suitable for a channel Name, rather than a label
    Essentially, this removes all the hyphens, uppercases RHEL, RHN, ES, AS, WS, title cases the rest.
    """
    capwords = [ 'rhn', 'rhel', 'as', 'es', 'ws', 'lbg' ]
    # at the moment these are the only arches we have...
    arches = [ 'i386', 'x86_64' ]
    output = []
    for word  in re.split('[-_]', label):
        if word in capwords:
            output.append(word.upper())
        elif  word in arches:
            output.append(word)
        else:
            output.append(word.capitalize())
    return ' '.join(output)


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

    logging.debug("Got dest channel %s" % opts.dest)

    # initialiase an RHN Session
    try:
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache, debug=opts.debug)
        if opts.debug:
            RHN.enableDebug()

        channels = [ x['label'] for x in channel.listSoftwareChannels(RHN) ]
        # existing_channels = [ x['label'] for x in  channellist ]
        parents = channel.listBaseChannels(RHN)

        source_channels = []
        if opts.source not in channels:
            if opts.interactive:
                opts.src = utils.prompt_missing('Source Channel label: ')
            else:
                logging.error("source channel %s does not exist. Please try again" % opts.source)
                logging.error("The following channels exist on your satellite:")
                logging.error('\n'.join(channels))
                sys.exit(1)

        child_channels = []
        if opts.child:
            child_channels = channel.listChildChannels(RHN, opts.source)
            for child in child_channels:
                if child not in channels:
                    logging.error("child channel %s does not exist - should never get here!")
                    sys.exit(1)
        source_channels = [ opts.source ] + child_channels

        # If the --child option is specified, we treat opts.dest as a prefix for all source channels
        dest_channels = []
        if opts.child:
            for c in source_channels:
                if opts.dest:
                    logging.debug("source channel %s - dest channel %s" % (c, "_".join([opts.dest, c])))
                    dest_channels += [ "_".join([opts.dest, c]) ]
                elif opts.regex:
                    # Split the sed-style regex, expecting s/foo/bar
                    regex_split = opts.regex.split("/")
                    sedded_ch = c.replace(regex_split[1], regex_split[2])
                    logging.debug("Sedded %s = %s" % (c, sedded_ch))
                    dest_channels += [ sedded_ch ]
                else:
                    logging.error("Error, shouldn't get here, no destination or regex specifed!")
                    sys.exit(2)
        # Otherwise we take opts.dest to be the full destination name (original, pre --child behavior)
        elif opts.dest in channels:
            logging.warning("Destination Channel label %s already exists. Please Choose an alternative" % opts.dest)
            if opts.interactive:
               dest_channels += [ utils.prompt_missing('Destination Channel Label: ') ]
            else:
                sys.exit(2)
        else:
            if opts.dest:
                dest_channels += [ opts.dest ]
            elif opts.regex:
                # Split the sed-style regex, expecting s/foo/bar
                regex_split = opts.regex.split("/")
                sedded_ch = c.replace(regex_split[1], regex_split[2])
                logging.debug("Sedded %s = %s" % (c, sedded_ch))
                dest_channels += [ sedded_ch ]
            else:
                logging.error("Error, shouldn't get here, no destination or regex specifed!")
                sys.exit(2)
                  

        if opts.parent is not None and opts.parent not in parents:
            logging.warning("Parent Channel is not an existing Base Channel. Please choose one of the following:")
            logging.warning( '\n'.join(parents))
            if opts.interactive:
                opts.parent = utils.prompt_missing('Parent Channel Label: ')

        # In interactive mode, summarise what is about to be cloned and ask for confirmation
        if opts.interactive:
            print "You are about to perform the following channel clone operations:"
            for source,clone in zip(source_channels, dest_channels):
                print "Clone %s ==> %s" % (source, clone)
            if user_ask_ok("Confirm - Clone these channels (yes/no):") != True:
                logging.warning("Clone cancelled by user, exiting")
                sys.exit(1)

        # okay, we have the information I need, let's try...
        parent_channel = None
        if opts.parent:
            parent_channel = opts.parent

        for source,clone in zip(source_channels, dest_channels):
            timestr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            summary="Clone of %s, created on %s" % (source, timestr)
            name=label_to_name(clone)
            kwargs = {'label' : clone, 'name': name, 'summary': summary }
            if parent_channel:
                kwargs['parent_label'] = parent_channel

            # Populate the kwargs GPG info from the channel we're cloning, important to do this now
            # since there appears to be no way to fix this up later via the API :(
            details = channel.detailsByLabel(RHN, source)
            if details['gpg_key_url']:
                logging.debug("details gpg_key_url true == %s" % details['gpg_key_url'])
                kwargs['gpg_url'] = details['gpg_key_url']
            if details['gpg_key_id']:
                logging.debug("details gpg_key_id true == %s" % details['gpg_key_id'])
                kwargs['gpg_id'] = details['gpg_key_id']
            if details['gpg_key_fp']:
                logging.debug("details gpg_key_fp true == %s" % details['gpg_key_fp'])
                kwargs['gpg_fingerprint'] = details['gpg_key_fp']

            # Print what we are about to do and prompt for a yes/no confirmation if --confirm
            logging.debug("cloning channel %s -> %s, name \"%s\", parent %s, summary\"%s\"" % (source, clone, name, parent_channel, summary))
            if channel.cloneChannel(RHN, source, False, **kwargs):
                logging.info("Successfully cloned %s as %s" %(source, clone))
            else:
                logging.error("Error cloning %s as %s" %(source, clone))

            # If this is the first iteration in --child mode, 
            # we set the parent-channel to the first clone (base) channel
            if source == source_channels[0] and opts.child:
                logging.debug("First iteration in child mode, changing parent channel from %s to %s" % (parent_channel, clone))
                parent_channel = clone

    except KeyboardInterrupt:
        logging.debug("operation cancelled")
        sys.exit(1)

