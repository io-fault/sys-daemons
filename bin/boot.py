"""
# Service management daemon, &.root.Set.

# By default, this executable resolves the root service from the
# (system/environment)`FAULT_DAEMON_DIRECTORY` environment variable. A parameter
# may be provided to override that setting and the default (system/path)`~/.fault`.

# This module is intended for use with system invocation only.
"""
import os
import sys
from .. import service
from ...system import process

def main(inv:process.Invocation) -> process.Exit:
	detach = True

	# Root Service Invocation; resolve the hardlink and exec() as sectord.
	os.environ['PYTHON'] = sys.executable

	r = service.identify_route(*inv.argv) # One optional argument.
	os.environ['DAEMONS'] = str(r)

	rs = service.Configuration(r, None)
	if not rs.exists():
		sys.stderr.write("[!# ERROR: daemon set not initialized (critical)]\n")
		return inv.exit(78) # EX_CONFIG

	os.environ['SERVICE_NAME'] = 'rootd'
	rs.load()
	try:
		rs.load_pid()
		try:
			os.kill(rs.pid, 0)
			sys.stderr.write("[!# ERROR: root daemon is already running (critical)]\n")
			return inv.exit(128)
		except ProcessLookupError:
			pass
	except ValueError:
		# Invalid pidfile
		pass

	if detach:
		if os.fork() != 0:
			inv.exit(0)

		os.setsid()

		# Replace standard error.
		fd = os.open(str(r/'critical.log'), os.O_CREAT|os.O_APPEND|os.O_WRONLY)
		if fd != 2:
			os.dup2(fd, 2)
			os.close(fd)

	rs.execute()

	raise RuntimeError("program reached area after exec")

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
