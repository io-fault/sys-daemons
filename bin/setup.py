"""
# Initialize a root daemon directory.
"""
from fault.system import process
from fault.system.files import Path
from .. import service

def configure_root_service(srv):
	"""
	# Given a &Service selecting an uninitialized file system path,
	# configure the path as a root sector daemon.
	"""

	srv.create()
	srv.actuation = 'enabled'
	srv.executable = 'libexec/rootd'
	srv.parameters = [__package__+'.rootd']
	srv.store()

	# The services controlled by &srv
	ddir = (srv.route / 'daemons')

	# When using the default home route, ~/.daemons is used
	# in order to avoid directory depth.
	if srv.route is service.default_route:
		home = ddir ** 3
		ltarget = ddir
		ddir = (home / '.daemons')
		ltarget.fs_link_relative(ddir)
	else:
		pass

	ddir.fs_mkdir()

def main(inv:process.Invocation) -> process.Exit:
	inv.imports(service.environment)

	try:
		path, = inv.argv
	except ValueError:
		path = None

	r = service.identify_route(path)
	srv = service.Configuration(r, 'rootd')
	configure_root_service(srv)

	return inv.exit(0)

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
