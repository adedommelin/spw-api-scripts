README for templates subdirectory

This directory contains templates for 
1. RHN api scripts in python, using the rhnapi module, containing:
- a basic commandline parser
- a "main" section that initializes your RHNAPI session

2. Your (optional) local config file to avoid repeatedly typing in passwords etc
save this as ~/.rhninfo, permissions at most 600 (it contains sensitive info)
for each server you need to access, add  a new [servername] section.
The api is not yet smart enough** to note parity between short and fully-qualified
hostnames, so if you intend to use both, you'll need 2 sections.



** and probably never will be, that way lies danger, Will Robinson.
