"""
# Initialize a root daemon directory.
"""
from ...system import process
from ...system.files import Path
from .. import service

def configure_root_service(srv):
	"""
	# Given a &Service selecting an uninitialized file system path,
	# configure the path as a root sector daemon.
	"""

	srv.create()
	srv.actuation = 'enabled'
	srv.executable = 'libexec/rootd' # reveal original executable
	srv.parameters = [__package__+'.rootd']
	srv.store()

	# The services controlled by &srv
	(srv.route / 'daemons').init('directory')

def main(inv:process.Invocation) -> process.Exit:
	path, = inv.args
	r = Path.from_path(path)
	srv = service.Configuration(r, 'rootd')
	configure_root_service(srv)

	return inv.exit(0)

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
