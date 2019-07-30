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
	# Root Service Invocation; resolve the hardlink and exec() as sectord.
	params = inv.args
	os.environ['PYTHON'] = sys.executable

	r = service.identify_route(*params[:1])
	os.environ['DAEMONS'] = str(r)

	rs = service.Configuration(r, None)
	if not rs.exists():
		sys.stderr.write("[!# ERROR: daemon set not initialized (critical)]\n")
		return inv.exit(78) # EX_CONFIG

	os.environ['SERVICE_NAME'] = 'rootd'
	rs.load()
	rs.execute()

	raise RuntimeError("program reached area after exec")

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
