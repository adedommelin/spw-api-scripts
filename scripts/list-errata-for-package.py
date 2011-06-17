#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
list-errata-for-package.py
An RHN API package to provide free-form lucene package searches and print out
the errata that provide a given package, to make cloning easier.

Uses the rhnapi python module, so ensure this is on your PYTHONPATH
The information this provides can be used to 
"""

__author__ = "Stuart Sears <sjs@redhat.com>"

import sys
import os
# for matching RPM package name strings
# import re
# for commandline parsing
from optparse import OptionParser, OptionGroup
# for pretty-printing debug output
from pprint import pprint
# for sorting the results
from operator import itemgetter


import rhnapi
from rhnapi import packages

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
    preamble = "Search for packages on your satellite and list the errat(a|um) that provides them, if any"
    usagestr = "%prog [RHNOPTS] -n packagename [-v VERSION] [-r RELEASE ] -a [ARCH]"
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
    pkggrp = OptionGroup(parser, "Package selection")
    pkggrp.add_option("-n", "--name", help = "Package Name to search for")
    pkggrp.add_option("-V", "--version", help = "Package Version")
    pkggrp.add_option("-r", "--release", help = "Package Release")
    pkggrp.add_option("-a", "--arch", help = "Package Arch")
    pkggrp.add_option("-q", "--query", help = "Raw lucene format query. Overrides the other options")
    pkggrp.add_option("-f", "--filename", help = "figure out package names etc from a filename (the RPM package name)")
    parser.add_option_group(pkggrp)

    if len(argv) == 0:
        parser.print_help()
        sys.exit(1)
    opts, args = parser.parse_args(argv)
    # check the args for errors etc...

    # finally...
    return opts, args
        
# --------------------------------------------------------------------------------- #

def query_from_filename(fname):
    """
    parses a standard RPM filename (with or without the '.rpm' extension)
    returns a logical ANDed lucene query string like this:
    'name:"name" AND version:"version" AND...'
    """
    # an empty dict to store the values in - makes string formatting easier.
    pkginfo = {}
    # first, strip off the .rpm if it's there
    if fname.endswith('.rpm'):
        fname = os.path.splitext(fname)[0]

    # pull the arch off the end
    # for some reason this includes the '.', so strip it too.
    fname, farch = os.path.splitext(fname)
    if farch != '':
        pkginfo['arch'] = farch.lstrip('.')

    # now split by hyphens and work backwards (as names can contain - symbols too)
    # This is quite ugly but appears to work
    splitname = fname.split('-')

    # the releas should be the last entry
    pkginfo['release'] = splitname.pop()

    # then the version string
    version = splitname.pop()
    pkginfo['name'] = '-'.join(splitname)
    # if there's an epoch it'll be at the front of the version string
    if len(version.split(':')) == 2:
        pkginfo['epoch'], pkginfo['version'] = version.split(':')
    else:
        pkginfo['epoch'] = ''
        pkginfo['version'] = version
        
    # return the dict parsed into a query string
    strparts = []
    for k, v in pkginfo.iteritems():
        # don't include any elements that were blank
        if v != '':
            strparts.append("%s:%s" % (str(k), v))
    # finally, join it all together
    return ' AND '.join(strparts)
        
# --------------------------------------------------------------------------------- #

if __name__ == '__main__':
    
    opts, args = parse_cmdline(sys.argv[1:])
    # initialiase an RHN Session
    try:
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache)
        # assemble our package query in lucene format
        if opts.debug:
            RHN.enableDebug()
        # were we given a proper lucene query string?
        if opts.query:
            querystr = opts.query
        # if called with a filename argument, use that
        elif opts.filename:
            querystr = query_from_filename(opts.filename)
            print querystr
        # finally we parse the other nvrea args
        else:
            queryitems = []
            if opts.name:
                queryitems.append('name:"%s"' % opts.name)
            if opts.version:
                queryitems.append('version:"%s"' % opts.version)
            if opts.release:
                queryitems.append('release:"%s"' % opts.release)
            if opts.arch:
                queryitems.append('arch:"%s"' % opts.arch)
            querystr = ' AND '.join(queryitems)

        if opts.verbose:
            print "Querying with search string: %s" 

        # perform a lucene query using our query string:
        matched_packages = packages.search(RHN, querystr)
        
        # if the search worked, but returned nothing...
        if matched_packages and len(matched_packages) == 0:
            print "No packages seem to match the provided search parameters (%s)" % querystr
        else:
            print "Packages matching your query"
            for pkg in sorted(matched_packages, key=itemgetter('version')):
                pkgstr = "%(id)-10d   %(name)s-%(version)s-%(release)s.%(arch)s" % pkg
                print "Package ID   Package Name"
                print "----------   ------------"
                print pkgstr
                providing_errata = packages.listProvidingErrata(RHN, pkg['id'])
                if len(providing_errata) == 1:
                    term = 'Erratum'
                else:
                    term = 'Errata'
                print
                print "%s providing this package (for cloning purposes)" % term
                print "Advisory Name    Description"
                print "-------------    -----------"
                for errobj in providing_errata:
                    print "%(advisory)-15s  %(synopsis)s" % errobj
                print "----------------------------\n"

    except KeyboardInterrupt:
        print "operation cancelled"
        sys.exit(1)


    
    
    
