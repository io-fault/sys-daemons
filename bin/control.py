"""
# Server Control Command

# Similar to &.service, but works with a running faultd instance.
# Communicates with the running daemon using its file system sockets
# or an arbitrary endpoint usually protected with a client certificate.
# requirement.

# Control only issues commands to faultd which may in turn connect
# to the service's process in order to issue the actual command.

# Control can dispatch commands or wait for their completion.

# .control (uri|env) start|restart|stop|reload <service_name> "comment"
# .control (uri|env) wait <service_name> # waits until the service's process exits
# .control (uri|env) disable|enable <service_name> "comment"
# .control (uri|env) signal <service_name> signo "comment"
"""

from ...system import process

def main(inv:process.Invocation) -> process.Exit:
	return inv.exit(254)
	from ...kernel import system
	system.dispatch(inv, dl)
	system.control()

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
