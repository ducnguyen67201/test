#!/bin/bash
# OctoLab command logging compatibility shim
# Sources the canonical script from /etc/profile.d/
#
# This file is sourced from /etc/bash.bashrc to ensure command logging
# works in XFCE Terminal (interactive non-login shells)

[ -f /etc/profile.d/octolab-cmdlog.sh ] && . /etc/profile.d/octolab-cmdlog.sh
