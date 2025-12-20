#!/bin/sh

if [ -r /etc/default/locale ]; then
  . /etc/default/locale
  export LANG LANGUAGE
fi

# Start XFCE session for XRDP with a per-session DBus bus.
# dbus-launch creates a session bus and exports DBUS_SESSION_BUS_ADDRESS
# --exit-with-session ensures the bus is torn down when XFCE exits.
exec dbus-launch --exit-with-session startxfce4

