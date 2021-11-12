"""
# Initialize a root daemon directory for managing a set of services.
"""
from fault.system import process

from .. import service

def configure_root_service(srv):
	"""
	# Given a &Service selecting an uninitialized file system path,
	# configure the path as a root sector daemon.
	"""

	srv.create()
	srv.actuation = 'enabled'
	srv.executable = 'libexec/rootd'
	srv.parameters = [__package__ + '.rootd']
	srv.store()

	# The services controlled by &srv
	ddir = (srv.route / 'daemons')

	# When using the default home route, ~/.daemons is used to avoid the
	# additional directory depth. ~/.daemons vs ~/.rootd/daemons.
	if srv.route == service.default_route:
		ddir.fs_link_relative(service.default_daemons)
		service.default_daemons.fs_mkdir()
	else:
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
