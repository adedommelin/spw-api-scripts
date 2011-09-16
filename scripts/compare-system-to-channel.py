#!/usr/bin/env python
# template API script using the rhnapi python module
# the module will need to be on your PYTHONPATH
# or its parent directory added using sys.path.append
"""
compare-system-to-channel.py
A script to diff the package list from a server and the packages in
its subscribed base channel, and optionally any subscribed child channels
to see what is missing, out of date, or has been updated out-of-band
Can also diff with another selected channel if required.

requires the rhnapi python module.
"""
# standard library imports
import sys
import os
from optparse import OptionParser, OptionGroup
from operator import itemgetter
from pprint import pprint
import rpm
import logging

# custom module imports
import rhnapi
from rhnapi import system
from rhnapi import channel
from rhnapi import packages
from rhnapi import utils

from progressbar import Counter,Percentage,ProgressBar, Timer, AnimatedMarker, Bar

# configuration variables. Probably okay, actually.
RHNCONFIG = '~/.rhninfo'
RHNHOST = 'localhost'
# put these in your configfile, dammit;
RHNUSER = None
RHNPASS = None

# --------------------------------------------------------------------------------- #
def parse_cmdline(argv):
    """
    process the commandline :)
    """
    preamble = """processes all systems with the chosen base channel.
Returns a list of all packages on the system but not in the base channel,
plus any errata that provide those packages (if there are any)."""
    usagestr = "%prog [RHNOPTS...] [SYSTEMOPTS...]"
    # initialise our parser and set some default options
    parser = OptionParser(usage = usagestr, description = preamble)
    parser.add_option("--debug", action = "store_true", default = False,
            help = "enable debug output for RHN session (XMLRPC errors etc")
    parser.add_option("-v", "--verbose", action = "store_true", default = False,
            help = "enable informational output for RHN session (XMLRPC errors etc")

    # RHN Satellite options group
    rhngrp = OptionGroup(parser, "RHN Satellite Options", "Defaults can be set in your RHN API config file (%s)" % RHNCONFIG )
    rhngrp.add_option("--server",help="RHN satellite server hostname [%default]", default=RHNHOST)
    rhngrp.add_option("--login", help="RHN login (username)" , default=RHNUSER)
    rhngrp.add_option("--pass", dest = "password", help="RHN password. This is better off in a config file.", default=RHNPASS)
    rhngrp.add_option("--config", dest = "config", help="Local RHN configuration file [ %default ]", default=RHNCONFIG)
    rhngrp.add_option("--cache", action = "store_true", default = False, help = "save usernames and password in config file, if missing")
    parser.add_option_group(rhngrp)

    # script-specific options
    sysgrp = OptionGroup(parser, "System and Channel selection")
    sysgrp.add_option("-f", "--output", default = None, help = "output data to this filename as JSON, for later use")
    sysgrp.add_option("-r", "--report", action = "store_true", default = False, help = "Output a somewhat formatted report output on stdout, can be used with -o")
    sysgrp.add_option("-p", "--profile", default = None, help = "only process this system profile name.")
    sysgrp.add_option("-i", "--system_id", default = None, help = "only process this system profile ID (useful if there are duplicate systems with the same name)")
    sysgrp.add_option("-c", "--channel", default = None, help="channel name to diff against. Optional - only if not the system's current base channel")
    sysgrp.add_option("-C", "--child", action = "store_true", default = False, help="Include child channels, subscribed channels if per-system, or all children of the channel in conjunction with --channel")
    sysgrp.add_option("-a", "--all", dest = "consolidate", default = False, action = "store_true", help = "just summarize all provided systems, not one at a time")
    parser.add_option_group(sysgrp)

    # this is quite a long-running script, so offer to show a progressbar if needed.
    parser.add_option("-P", "--progress", action = "store_true", default = False,
            help = "show progress bars for long-running processes. Conflicts with --debug.")

    opts, args = parser.parse_args()
    # check the args for errors etc...
    if not opts.channel and not ( opts.profile or opts.system_id):
        print "you must provide either a system profile name, an ID or a channel label."
        parser.print_help()
        sys.exit(1)

    # finally...
    return opts, args

# --------------------------------------------------------------------------------- #
def get_pkgids(rhn, packagelist, progressbar = True):
    """
    As system.listPackages doesn't give package IDs, I need to search for each pkg
    using findByNvrea
    This shows a progressbar by default
    """
    if progressbar:
        widgets = ['Getting Package Details: ', Counter(), ' packages [', Percentage(), ']', '(', Timer(), ')']
        pbar = ProgressBar(widgets=widgets, maxval=len(packagelist), term_width=80).start()
    for pkg in packagelist:
        if progressbar:
            count = packagelist.index(pkg) + 1
        # handle AMD64 as an arch label (why does satellite not handle this automatically?)
        if pkg['arch'].strip() == 'AMD64':
            arch = 'x86_64'
        else:
            arch = pkg['arch']
        searchdata = packages.findByNvrea( rhn, pkg['name'], pkg['version'], pkg['release'], arch, pkg['epoch'])
        if len(searchdata) != 1:
            continue
        else:
            pkginfo = searchdata[0]
        if isinstance(pkginfo, dict):
            for k, v in pkginfo.iteritems():
                if pkg.has_key(k):
                    continue
                else:
                    pkg[k] = v
        if progressbar:
            pbar.update(count)
    #print
    return packagelist

# --------------------------------------------------------------------------------- #
def check_unknown(pkglist):
    """
    returns True if there are no packages of 'unknown' arch in a package list.
    (handles old broken versions of up2date)
    """
    for x in pkglist:
        if x['arch'].lower() == 'unknown':
            return False
    return True

# --------------------------------------------------------------------------------- #
def diff_missing_pkgs(system_pkgs, channel_pkgs):
    """
    Take 2 package lists and calculate stuff in pkglist1 not in pkglist 2
    Specifically this will include updates beyond the channel update level
    """
    pkgs1 = set([ x['id'] for x in system_pkgs if x.has_key('id') ])
    pkgs2 = set([ x['id'] for x in channel_pkgs if x.has_key('id')])
    pkgdiffs = [ x for x in system_pkgs if x.has_key('id') and x['id'] in pkgs1.difference(pkgs2) ]
    return pkgdiffs

# --------------------------------------------------------------------------------- #
def latest_channel_pkg(pkg, channel_pkgs):
    """
    Match packages in channel_pkgs with the same name as pkg, if there is more than one
    we return the latest version in the channel
    Note this is probably best run on the reduced channel list as it will be faster 
    since the "channel latest" comparison has already been done for us
    """
    matchpkgs = [ x for x in channel_pkgs if x.has_key('id') and x['name'] == pkg['name'] ]
    latestpkg=None
    if len(matchpkgs) == 0:
        logging.debug("Failed to find channel package for %s" % pkg['name'])
    elif len(matchpkgs) == 1:
        logging.debug("Found one channel package for %s" % pkg['name'])
        latestpkg=matchpkgs[0]
    else:
        # If matchpkgs is longer than one, reduce it with latest_pkg
        logging.debug("Found %d channel packages for %s" % (len(matchpkgs), pkg['name']))
        latestpkg=matchpkgs[0]
        for match in matchpkgs:
            cmppkg = latest_pkg(match,latestpkg)
            if cmppkg != None:
                latestpkg = cmppkg

    return latestpkg

# --------------------------------------------------------------------------------- #

def latest_pkg(pkg1, pkg2):
    """
    Compares 2 package objects (dicts) and returns the newest one.
    If the objects are the same, we return None
    Comparisons are done using RPM label compares (architecture is not relevant here)
    This is only useful for comparing 2 versions of the same package, or results might
    be a little confusing.
    """
    # Sometimes empty epoch is a space, and sometimes its an empty string, which 
    # breaks the comparison, strip it here to fix
    t1 = (pkg1['epoch'].strip(), pkg1['version'], pkg1['release'])
    t2 = (pkg2['epoch'].strip(), pkg2['version'], pkg2['release'])

    result = rpm.labelCompare(t1, t2)
    if result == 1:
        return pkg1
    elif result == -1:
        return pkg2
    else:
        return None

# --------------------------------------------------------------------------------- #

def index_by_arch(pkglist, progressbar = False):
    """
    returns an index of the given package list (for ease of reduction)
    extend this for
    { 'name' : { 'arch' : [], 'arch' :[] ] ?
    """
    pkgindex = {}
    if progressbar:
        widgets = ['Indexing packages by architecture: ', Counter(), ' packages [', Percentage(), ']', '(', Timer(), ')']
        pbar = ProgressBar(widgets=widgets, maxval=len(pkglist), term_width=80).start()
    logging.debug("indexing package list (%d items) by name and architecture" % len(pkglist))
    for pkg in pkglist:
        name = pkg['name']
        arch = pkg['arch_label']

        # ensure there is an entry for this package name
        if not pkgindex.has_key(name):
            pkgindex[name] = {}
        # if there isn't an appropriate arch subkey, create that too
        if not pkgindex[name].has_key(arch):
            pkgindex[name][arch] = []

        pkgindex[pkg['name']][pkg['arch_label']].append(pkg)
        if progressbar:
            pbar.update(pkglist.index(pkg) +1)
    logging.info("indexed %d packages" % len(pkgindex))
    return pkgindex

# --------------------------------------------------------------------------------- #

def reduce_by_arch(pkglist, progressbar = False):
    """
    returns a reduced package list, containing the latest version of any package for each architecture.
    (i.e. if zsh is in the channel both in i386 and x86_64 arches, returns the latest version for each.
    Which should really be the same, but just in case...)
    """
    # first, index the package list by name for ease of comparison:
    pkgindex = index_by_arch(pkglist, progressbar = progressbar)

    reduced_list = []
    if progressbar:
        widgets = ['Reducing package list to latest versions: ', Counter(), ' packages [', Percentage(), ']', '(', Timer(), ')']
        pbar = ProgressBar(widgets=widgets, maxval=len(pkgindex), term_width=80).start()
        counter = 0
    logging.info("reducing package list (%d items) to latest versions only (for each architecture)" % len(pkglist))
    for pkgname, archdict in pkgindex.iteritems():
        for arch, pkgobjs in archdict.iteritems():
            if len(pkgobjs) == 0:
                # then we have an empty list. Should never happen, but...
                continue
            if len(pkgobjs) == 1:
                # there's only one version of this package installed
                reduced_list.append(pkgobjs[0])
            else:
                newest = pkgobjs[0]
                for pkg in pkgobjs[1:]:
                    res = latest_pkg(newest, pkg)
                    if res is not None:
                        newest = res
                reduced_list.append(newest)
        if progressbar:
            counter += 1
            pbar.update(counter)
    logging.info("reduced packagelist to %d entries" % len(reduced_list))
    return reduced_list

# --------------------------------------------------------------------------------- #
def pkg_errata(rhn, pkg):
    """
    Returns a list of errata which provide the package pkg
    """
    errnames = []
    errlist = packages.listProvidingErrata(RHN, pkg['id'])
    if len(errlist) > 0:
        errnames = [ x['advisory'] for x in errlist ]
    return errnames
        
# --------------------------------------------------------------------------------- #
def process_system(rhn, systemobj, reducedpackagelist, progressbar = False, packagedict = {}, report = False):
    """
    Abstracts the system processing parts
    This is run per system and compares its package set to the (reduced) channel package list,
    returning the diffs as a dictionary. Can optionally use a global dictionary object when repeatedly
    run across a number of systems.
    """
    results = packagedict
    installed_pkgs = system.listPackages(RHN, systemobj['id'])
    if check_unknown(installed_pkgs):
        if report:
            print "SYSTEM_PACKAGE STATUS CHANNEL_LATEST ERRATA_CONTAINING_NEWEST"
        sys_pkgs = get_pkgids(RHN, installed_pkgs, progressbar = progressbar)
        for pkg in sorted(sys_pkgs, key=itemgetter('name')):

            pkgstr = "%(name)s-%(version)s-%(release)s.%(arch_label)s" % pkg

            # Find the latest package in the channel list matching this package name
            # This will allow us to determine if a package has been updated beyond the
            # channel latest out of band (rather than just saying "missing" we can say "newer"
            # also it allows us to show the latest in the channel when a package is out of date
            channel_latest = latest_channel_pkg(pkg, reducedpackagelist)
            if channel_latest:
                # We matched another package with the same name, is it older or newer?
                chpkgstr = "%(name)s-%(version)s-%(release)s.%(arch_label)s" % channel_latest
                latestpkg = latest_pkg(channel_latest, pkg)
                if latestpkg != None:
                    if ( latestpkg == channel_latest ):
                        logging.info("%s is OLDER than channel latest version %s" % (pkgstr, chpkgstr))
                        pkgerrata = pkg_errata(RHN, channel_latest)
                        if report:
                            print "%s OLDER_THAN_CHANNEL_LATEST %s %s" % (pkgstr, chpkgstr, ",".join(pkgerrata))
                        if results.has_key('older'):
                            if pkgstr not in results['older']:
                                results['older'].append(pkgstr)
                        else:
                            results['older'] = [ pkgstr ]
                    elif ( latestpkg == pkg ):
                        logging.info("%s is newer than channel latest version %s" % (pkgstr, chpkgstr))
                        pkgerrata = pkg_errata(RHN, pkg)
                        if report:
                            print "%s NEWER_THAN_CHANNEL_LATEST %s %s" % (pkgstr, chpkgstr, ",".join(pkgerrata))
                        if results.has_key('newer'):
                            if pkgstr not in results['newer']:
                                results['newer'].append(pkgstr)
                        else:
                            results['newer'] = [ pkgstr ]
                else:
                    logging.info("%s is the SAME as channel version %s" % (pkgstr, chpkgstr))
            else:
                # There's nothing with the same name, so it really is missing from the channel
                pkgerrata = pkg_errata(RHN, pkg)
                logging.info("%s is not found in channel" % pkgstr)
                if report:
                    print "%s NOT_FOUND_IN_CHANNEL None %s" % (pkgstr, ",".join(pkgerrata))
                if results.has_key('missing'):
                    if pkgstr not in results['missing']:
                        results['missing'].append(pkgstr)
                else:
                    results['missing'] = [ pkgstr ]

    else:
        print "system %s has an outdated version of up2date, please update it" % systemobj['name']
        return None

    return results

# --------------------------------------------------------------------------------- #

if __name__ == '__main__':
    
    # parse the command line
    opts, args = parse_cmdline(sys.argv)
    if opts.debug:
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)
        opts.verbose=True # For pprint below
        logging.debug("Debug level logging enabled")
    elif opts.verbose:
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)
    else:
        logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.WARNING)

    # initialise an RHN Session (the try...except block allows us to interrupt with Ctrl-C)
    try:
        RHN = rhnapi.rhnSession(opts.server, opts.login, opts.password, config=opts.config, cache_creds=opts.cache, debug=opts.debug)
        # did we require debugging? lots of unpleasant output on failure if we did...
        if opts.debug:
            RHN.enableDebug()

        if opts.profile or opts.system_id:
            # then we are only querying one system, lookup by name or ID
            try:
                # lookup the systemid for this system, taking the one that most recently checked in,
                # if there is more than one. (This call always returns a list, or throws an exception)
                if opts.system_id:
                    # lookup the system via ID using system.getName, this returns an object of the same type as getId, and 
                    # since the systemobj['id'] is used hereafter, it should cope with duplicate system names
                    logging.debug("getting systemobj by ID %s" % opts.system_id)
                    systemobj = system.getName(RHN, int(opts.system_id))
                else:
                    logging.debug("getting systemobj by name %s" % opts.profile)
                    systemobj = sorted(system.getId(RHN, opts.profile), key=itemgetter('last_checkin'), reverse = True)[0]
                logging.debug("Got ID %s for system %s" % (systemobj['id'], systemobj['name']))
            except:
                print "unable to lookup system record. Please check ID/Profile argument and try again"
                sys.exit(3)

            system_list = [ systemobj ]
            childchannels = []
            # if we didn't choose a channel to diff against, use the system's base channel:
            if not opts.channel:           
                basechannel = system.getBaseChannel(RHN, systemobj['id'])
                logging.info("using base channel %s for %s" %( basechannel, opts.profile))
                if opts.child:
                    childchannels = system.getChildChannels(RHN, systemobj['id'])
                    logging.info("using child channels %s for %s)" %( childchannels, opts.profile))

        if opts.channel:
            # we are specifying a channel, this means either all systems subscribed, or if -p/-i specified
            # then we diff a specific system against a channel other than it's subscribed channel(s)
            basechannel = opts.channel
            if opts.child:
                # TODO: the --child feature only works per system at the moment, I guess we just list all channel children here?
                logging.warning("child recursion not yet implemented for --channel mode")
            if opts.profile or opts.system_id:
                # then we should already have a  'systemobj' record
                system_list = [ systemobj ]
            else:
                system_list = channel.listSubscribedSystems(RHN, basechannel)

        # was used for progress reports...
        syscount = len(system_list)

        logging.info("Getting a list of packages in channel %s" % basechannel)
        chan_pkgs = channel.listAllPackages(RHN, basechannel)
        for child in childchannels:
            logging.debug("Adding packages from child channel %s" % child)
            chan_pkgs += channel.listAllPackages(RHN, child)

        logging.debug("reducing package list to latest available versions only")
        reduced_pkgs = reduce_by_arch(chan_pkgs, opts.progress)

        # now process each system
        counter = 1
        global systemdiff
        systemdiff = {}
        for sysrecord in system_list:
            logging.debug("finding package differences for %s [%d of %d]" % (sysrecord['name'], counter, syscount))
            if opts.report:
               print "SYSTEM(%s,%d) : ----- : CHANNELS(%s,%s)" % (sysrecord['name'], systemobj['id'], basechannel, ",".join(childchannels)) 
            process_system(RHN, sysrecord, reduced_pkgs, progressbar = opts.progress, packagedict = systemdiff, report = opts.report)
            logging.debug("package diff now has %d entries" %  len(systemdiff))
            counter += 1

        if opts.verbose:
            pprint(systemdiff)

        if opts.output:
            logging.info("dumping JSON records to output file %s" % opts.output)
            if os.path.exists(opts.output):
                res = prompt_confirm('overwrite existing file %s' % opts.output)
            else:
                res = True
            if res:
                utils.dumpJSON(systemdiff, opts.output)


        # DO STUFF with your RHN session and commandline options
    except KeyboardInterrupt:
        print "operation cancelled"
        sys.exit(1)


    
    
    
