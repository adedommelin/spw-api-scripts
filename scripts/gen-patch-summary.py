#!/usr/bin/env python
# template API script using the rhnapi python module
# the module will need to be on your PYTHONPATH
# or its parent directory added using sys.path.append
__doc__ = """Designed to produce a list of unsynced errata from a source channel
since the given start date (defaults to the first of the current calendar month)
and produce a CVS output from them
Can read channel mappings from a JSON-format config file like this:
(only the section for 'lgb-3.0' is shown
{
    "lgb-3.0": {
        "source": "rhel-x86_64-server-5", 
        "chan": "lgb-rhel-x86_64-server-5"
        "children": [
            {
                "source": "rhel-x86_64-server-productivity-5", 
                "chan": "lgb30-rhel-x86_64-server-productivity-5"
            }, 
            {
                "source": "rhn-tools-rhel-x86_64-server-5", 
                "chan": "lgb30-tools-rhel-x86_64-server-5"
            }
        ]
    }, 
}
"""
__author__ = "Stuart Sears <stuart.sears@man.com>"

# standard library imports
import sys
import os
from optparse import OptionParser, OptionGroup
from ConfigParser import SafeConfigParser
import time
import csv

try:
    import json
except ImportError:
    import simplejson as json



# custom module imports
import rhnapi
from rhnapi import channel

# configuration variables. Probably okay, actually.
RHNCONFIG = '~/.rhninfo'
RHNHOST = 'localhost'
# put these in your configfile, dammit;
RHNUSER = None
RHNPASS = None

CHANNELMAPS = [ os.path.expanduser('~/.rhn-channels.conf'), '/etc/sysconfig/rhn-channels.conf' ]

# --------------------------------------------------------------------------------- #
def parse_cmdline(argv):
    """
    process the commandline :)
    """
    preamble = "Generate a CVS list of unsynced errata for a given channel since the given date"
    usagestr = "%prog [RHNOPTS]"
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
    changrp = OptionGroup(parser, "Channel Selection Options")
    changrp.add_option("-c", "--channel", help = "cloned channel label to summarise")
    changrp.add_option("-s", "--source", help = "Source channel (where CHANNEL was cloned from")
    changrp.add_option("-d", "--date", help = "Only summarise errata released after this date")
    changrp.add_option("-o", "--output", help = "Output File for results")
    changrp.add_option("-m", "--channel-mapping", help = "INI-style file for grouping/mapping source and cloned channels", default = None)
    changrp.add_option("-g", "--group", help = "Channel group (from INI file) to summarise")
    parser.add_option_group(changrp)

    if len(argv) == 0:
        parser.print_help()
        sys.exit(0)

    opts, args = parser.parse_args(argv)
    # check the args for errors etc...
    if not opts.group:
        if not opts.channel:
            print "You must provide a channel to summarise"
            parser.print_help()
            sys.exit(2)

        if not opts.source:
            print "Which channel was %s cloned from?" % opts.channel
            parser.print_help()
            sys.exit(2)

    # convert to a list for use with SafeConfigParser
    if opts.channel_mapping:
        opts.channel_mapping = [ opts.channel_mapping ]
    else:
        opts.channel_mapping = CHANNELMAPS

    if not opts.output:
        print "no output file provided, using stdout"
        opts.output = sys.stdout

    # finally...
    return opts, args

def write_csv(data, filename, logger):
    """
    moved out of the main function for portability
    """
    fields = ['advisory', 'synopsis', 'issue_date', 'last_modified_date', 'urgency' , 'channel']
    try:
        if filename != sys.stdout:
            fd = open(filename, 'w')
        else:
            fd = filename
        mywriter = csv.DictWriter(fd, fieldnames = fields, extrasaction = 'ignore')
        fd.write("%s\n" % ','.join(fields))
        for row in data:
            syn = row['synopsis'].split(':')
            if len(syn) == 2:
                urg = syn[0]
            else:
                urg = 'None'
            row['urgency'] = urg
            mywriter.writerow(row)

        if fd != sys.stdout:
            fd.close()
            logger.info("wrote %d lines to %s" %(len(data), filename))
        return True            
        
    except:
        logger.critical("ERROR: could not write to file %s" % filename)
        return False
        
def diff_errata(rhn, chanlabel, source, date):
    """
    returns a dict of errata since the given date that have not been
    cloned from source to dest channels

    parameters:
    rhn(rhnapi.rhnSession)  - authenticated RHN session object
    chanlabel (str)         - channel label
    source(str)             - SOURCE channel label (usually where 'chanlabel' was cloned from)
    date(str)               - list errata since the given date fmt: YYYY-MM-DD HH:MM:SS
    """
    results = []
    chanerrata = channel.listErrata(rhn, chanlabel)
    chankeys = [ x['advisory'].split('-')[1] for x in chanerrata ]
    srcerrata = channel.listErrata(rhn, source, start_date = date)
    for e in srcerrata:
        if e['advisory'].split('-')[1] not in chankeys:
            e['channel'] = chanlabel
            results.append(e)

    return results




def main():
    """
    The core script content
    """
    # timestamp for use in filenames (logs, mostly)
    tstamp = time.strftime("%Y-%m-%d.%H%M%S")

    opts, args = parse_cmdline(sys.argv[1:])
    

    # this will always have a value
    channelmaps = None
    for c in opts.channel_mapping:
        if os.path.isfile(c) and os.access(c, os.R_OK):
            try:
                channelmaps = json.loads(open(c).read())
                break
            except:
                continue

    # if we read stuff in from a file:
    if channelmaps is not None:
        if opts.group:
            channelinfo = channelmaps.get(opts.group, {})
    else:
        # if not, use the command-line options provided
        channelinfo = {
                        'chan'     : opts.channel,
                        'source'   : opts.source,
                        'children' : [] }

    try:
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache, debug=opts.debug)
        RHN.addLogger("patch-review", "/tmp/patch-review-%s" % tstamp)
        # collect errata from cloned channel
        if opts.date:
            monthstart = "%s 00:00:00" % opts.date
            RHN.logInfo("Using date provided on commandline (%s)" % monthstart)
        else:            
            monthstart = "%s-01 00:00:00" % time.strftime("%Y-%m")
            RHN.logInfo("No date provided, defaulting to the beginning of this month (%s)" % monthstart)

        # now process our channels and their sources:
        # diff_errata(rhn, chanlabel, source, date)
        RHN.logInfo("processing Base Channel %s" % channelinfo['chan'])
        results = diff_errata(RHN, channelinfo['chan'], channelinfo['source'], monthstart)
        for k in channelinfo.get('children', []):
            RHN.logInfo("processing child channel %s" % k['chan'])
            kerr = diff_errata(RHN, k['chan'], k['source'], monthstart)
            if len(kerr) > 0:
                results += kerr

        # now we need to write a CSV file, use cvs.DictWriter, it'll be easier :)
        if write_csv(results, opts.output, RHN.logger):
            RHN.logInfo("CSV output successful")
       



    except KeyboardInterrupt:
        print "Operation cancelled by keystroke."
        sys.exit(1)
        
# --------------------------------------------------------------------------------- #

if __name__ == '__main__':
    # if the script is run directly, do this:
    main()


    
    
    
