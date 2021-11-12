"""
# Halt the user service daemon.
"""
import os
import sys
import signal

from fault.system import process

from .. import service

def main(inv:process.Invocation) -> process.Exit:
	running = False
	r = service.identify_route(*inv.argv) # One optional argument.
	rs = service.Configuration(r, None)

	if not rs.exists():
		sys.stderr.write("[!# ERROR: daemon set (%s) is not initialized]\n" %(str(r),))
		return inv.exit(78) # EX_CONFIG

	try:
		rs.load_pid()
		if rs.pid != 0:
			try:
				os.kill(rs.pid, signal.SIGTERM)
				running = True # No exception from kill?
			except ProcessLookupError:
				rs.pid = 0
				rs.store_pid()
	except ValueError:
		rs.pid = 0
		rs.store_pid()

	if not running:
		sys.stderr.write("[!# ERROR: root daemon (%s) is not running]\n" %(str(r),))
		inv.exit(128)

	return inv.exit(0)

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
