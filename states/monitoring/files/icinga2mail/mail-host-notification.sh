#!/bin/sh
template=`cat <<TEMPLATE
Notification Type: $NOTIFICATIONTYPE

Host: $HOSTALIAS
Address: $HOSTADDRESS
State: $HOSTSTATE

Date/Time: $LONGDATETIME

Additional Info: $HOSTOUTPUT

Comment: [$NOTIFICATIONAUTHORNAME] $NOTIFICATIONCOMMENT
TEMPLATE
`

/usr/bin/printf "%b" "$template" | mail -a "From: va-monitoring@domain.4com" -s "$NOTIFICATIONTYPE - $HOSTDISPLAYNAME is $HOSTSTATE" $USEREMAIL