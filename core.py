"""
# Service management interfaces.

# Manages the service state stored on disk.

# [ Properties ]

# /environment/
	# The environment variable that will be referenced in order
	# to identify the default service directory override.

# /default_route/
	# A &Path instance pointing to the default route
	# relative to the user's home directory. (~/.fault)
"""

import os
import sys
import itertools

from ..system.files import Path
from ..system import execution as libexec

from ..time import sysclock

environment = 'FAULT_DAEMON_DIRECTORY'
default_route = Path.home() / '.fault' / 'rootd'

def identify_route(override=None):
	"""
	# Return the service directory route.
	"""

	if override is not None:
		return Path.from_path(override)

	env = os.environ.get(environment)

	if env is None:
		return default_route

	return Path.from_path(env)

def service_routes(route=default_route):
	"""
	# Collect the routes to the set of services in the directory.
	"""

	# Only interested in directories.
	for i in route.subnodes()[1]:
		bn = i.basename
		yield bn, i

_actuation_map = {'enabled':True, 'disabled':False, True:'enabled', False:'disabled'}

def configure_root_service(srv):
	"""
	# Given a &Service selecting an uninitialized file system path,
	# configure the path as a root sector daemon.
	"""
	srv.create()
	srv.executable = sys.executable # reveal original executable
	srv.actuation = 'enabled'
	# rootd is a sector daemon.
	srv.parameters = [
		'-m', __package__+'.bin.sectord',
		__package__+'.libroot.Set.rs_initialize'
	]
	srv.store()

	# The services controlled by &srv
	(srv.route / 'daemons').init('directory')

	from . import daemon
	from ..kernel import io as kio
	cfg = srv.route / 'sectors.cfg'
	struct = {
		'concurrency': 0,
		'interfaces': {
			'http': [
				kio.endpoint('local', str(srv.route/'if'), 'http'),
			]
		},
	}
	cfg.store(b''.join(daemon.serialize_sectors(struct)))

class Service(object):
	"""
	# faultd service states manager.

	# Represents the faultd service stored on disk. The load and store methods are used
	# to perform the necessary updates to or from disk.
	"""

	def libexec(self, recreate=False, root=None):
		"""
		# Return the path to a hardlink for the service. Create if absent.
		"""

		r = self.route
		led = r / "libexec"
		exe = led / self.identifier

		fp = exe.fullpath

		if recreate:
			exe.void()

		if not exe.exists():
			led.init("directory")
			os.link(self.executable, fp)

		return fp

	def prepare(self):
		"""
		# Create the service directory.
		"""

		r = self.route

		r.init("directory")
		(r / 'libexec').init("directory")
		if_dir = (r / 'if')
		if_dir.init("directory")

	def void(self):
		"""
		# Destroy the service directory.
		"""

		self.route.void()

	def __init__(self, route:Path, identifier:str):
		"""
		# Initialize the Service structure selecting the &route as its
		# storage location. The &route may not exist upon instantiation
		# as it may be the first use in which the user may choose to
		# initialize a directory or merely check for whether it is
		# a service at all.
		"""
		self.route = route
		self.identifier = identifier

		self.executable = None
		self.environment = {}
		self.parameters = []

		self.abstract = None
		self.actuation = 'disabled'

	def critical(self, message):
		"""
		# Log a critical message. Usually used by &.bin.rootd and
		# &.bin.sectord.
		"""

		logfile = self.route / "critical.log"
		ts = sysclock.now().select('iso')

		with logfile.open('a') as f:
			f.write('%s: %s\n' %(ts, message))

	def trim(self):
		"""
		# Trim the critical log in the service's directory.

		# ! PENDING:
			# Not implemented.
		"""

		pass

	def execution(self):
		"""
		# Return a tuple consisting of the executable and the parameters.
		"""

		return self.executable, (self.parameters or [])

	def execute(self):
		"""
		# Execute the service replacing the process image. &execute does not return.

		# Environment variables will be updated by the running process,
		# the current working directory will be switched to service's directory,
		# &route, and the service with be executed according to the current
		# working settings assigned to &self.

		# A call to &load prior to running this is often reasonable.
		"""

		os.environ.update(self.environment or ())
		exe, params = self.execution()
		os.chdir(self.route.fullpath)
		os.execl(exe, *params)

		assert False

	def create(self):
		"""
		# Create the service directory and initialize many of the configuration files.
		"""

		self.actuation = 'disabled'
		self.prepare()
		self.store()

		self.critical("created service")

	def exists(self):
		"""
		# Whether or not the service directory exists.
		"""

		return self.route.exists()

	def load(self):
		"""
		# Load the service definition from the filesystem.
		"""

		self.load_actuation()
		self.load_invocation()

	def store(self):
		"""
		# Store the service definition to the filesystem.
		"""

		self.store_invocation()
		self.store_actuation()

	# one pair for each file
	invocation_attributes = (
		'abstract',
		'executable',
		'environment',
		'parameters',
	)

	@property
	def parts(self):
		return {
			x: self.__dict__[x]
			for x in self.invocation_attributes
		}

	def load_abstract(self):
		ar = self.route / "abstract.txt"
		self.abstract = ar.load().decode('utf-8')

	def load_invocation(self):
		inv_r = self.route / "if" / "invocation.txt"
		data = inv_r.load()
		if data:
			env, exe, params = libexec.parse_sx_plan(data.decode('utf-8'))
			self.executable = exe or None
			self.parameters = params
			self.environment = env

	def store_invocation(self):
		inv_r = self.route / "if" / "invocation.txt"
		env = self.environment or []
		exe = self.executable or ''
		params = self.parameters or []
		data = ''.join(libexec.serialize_sx_plan((env, exe, params)))
		inv_r.store(data.encode('utf-8'))

	def load_actuation(self):
		en_r = self.route / "actuation.txt"
		text = en_r.load().decode('ascii').strip().lower()
		self.actuation = text.strip().lower()

	def store_actuation(self):
		en_r = self.route / "actuation.txt"
		actstr = str(self.actuation).lower().encode('ascii')+b'\n'
		en_r.store(actstr)

	@property
	def actuates(self) -> bool:
		"""
		# Manage the actuation state of the service. &True means the
		# actuation.txt file contain `'enabled'`, &False means the
		# file contains `'disabled'`. Updating the property stores
		# the state to the file.
		"""
		global _actuation_map
		return _actuation_map.get(self.actuation, False)

	@actuates.setter
	def actuates(self, val:bool):
		global _actuation_map
		actstr = _actuation_map[val] # &val must be True or False.

		if actstr != self.actuation:
			# Update file if different from memory.
			self.actuation = actstr
			self.store_actuation()

	def load_pid(self):
		pid_r = self.route / "pid"
		self.pid = int(pid_r.load().decode('ascii').strip())

	def store_pid(self):
		pid_r = self.route / "pid"
		pid_r.store(str(self.pid).encode('ascii')+b'\n')

	@property
	def status(self):
		"""
		# Get and set the contents of the status file in the Service directory.
		"""

		return (self.route / "status").load().decode('utf-8').strip()

	@status.setter
	def status(self, val):
		status_r = self.route / "status"
		status_r.store(str(val).encode('utf-8')+b'\n')
