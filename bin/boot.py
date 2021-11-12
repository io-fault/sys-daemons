"""
# Start the user service daemon and detach the process from the terminal device.
"""
import os
import sys

from fault.system import process

from .. import service

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
