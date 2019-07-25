"""
# Root daemon process for service management and scheduled processes.

# &.root provides the primary support for &.bin.rootd which manages a set of daemons,

# Multiple instances of rootd may exist, but usually only one per-user is desired.
# The (system/home)`.fault` directory is used by default, but can be adjusted by a command
# line parameter. The daemon directory supplies all the necessary configuration,
# so few options are available from system invocation.
"""

import os
import sys
import signal
import functools
import itertools
import typing

from ..system import execution as libexec
from ..system.files import Path
from ..web import library as libweb

from ..kernel import core as kcore
from ..kernel import dispatch as kdispatch

from ..time import types as timetypes
from ..time import sysclock

from . import service

class Commands(libweb.Index):
	"""
	# HTTP Control API used by control (Host) connections.

	# GET Retrieves documentation, POST performs.
	"""

	def __init__(self, services, managed):
		self.managed = managed
		self.services = services

	@libweb.Resource.method()
	def sleep(self, resource, parameters) -> (str, str):
		"""
		# Send a stop signal associated with a timer to pause the process group.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.s_status == 'executed':
			service.subprocess.signal(signal.SIGSTOP)
			return (service.identifier, "service signalled to pause")
		else:
			return (service.identifier, "cannot signal service when not running")

	@libweb.Resource.method()
	def enable(self, resource, parameters) -> typing.Tuple[str, str]:
		"""
		# Enable the service, but do not start it.
		"""

		service = self.services[parameters['service']]
		service.actuates = True
		service.store_actuation()

		return (service.identifier, "enabled")

	@libweb.Resource.method()
	def disable(self, resource, parameters):
		"""
		# Disable the service, but do not change its status.
		"""

		service = self.services[parameters['service']]
		service.actuates = False
		service.store_actuation()

		return (service.identifier, "disabled")

	@libweb.Resource.method()
	def signal(self, resource, parameters):
		"""
		# Send the given signal to the process.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]
		signo = int(parameters['number'])

		if service.s_status == 'executed':
			managed.subprocess.signal(signo)
			return "service signalled"
		else:
			return "signal not sent as service has not been executed"

	@libweb.Resource.method()
	def stop(self, resource, parameters):
		"""
		# Signal the service to stop and inhibit it from being restarted if enabled.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.actuates:
			managed.inhibit_recovery = True
		else:
			# No need.
			managed.inhibit_recovery = None

		if managed.s_status != 'executed':
			return (service.identifier, "stop ineffective when not running")

		managed.subprocess.signal_process_group(signal.SIGTERM)
		return (service.identifier, "daemon signalled to terminate")

	@libweb.Resource.method()
	def restart(self, resource, parameters):
		"""
		# Signal the service to stop (SIGTERM) and allow it to restart.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.s_status != 'executed':
			return (service.identifier, "restart ineffective when not running")

		managed.inhibit_recovery = False
		managed.subprocess.signal_process_group(signal.SIGTERM)

		return (service.identifier, "daemon signalled to restart")

	@libweb.Resource.method()
	def reload(self, resource, parameters):
		"""
		# Send a SIGHUP to the service.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.subprocess is not None:
			managed.subprocess.signal(signal.SIGHUP)
			return (service.identifier, "daemon signalled to reload using SIGHUP")
		else:
			return (service.identifier, "reload ineffective when service is not running")

	@libweb.Resource.method()
	def replace(self, resource, parameters):
		service = self.services[parameters['service']]
		# substitute the sectord process (code/process update)
		# 1. write a substitution file to filesystem
		# 2. signal hup
		# 3. [sectord] check for substitution file on hup receive and begin natural halt
		# 4. [sectord] store environment state recording interfaces
		# 5. [sectord] exec to new process and load state from environment
		return (service.identifier, "substitute not supported")

	@libweb.Resource.method()
	def start(self, resource, parameters):
		"""
		# Start the daemon unless it's already running; explicit starts ignore
		# &service.Configuration.actuates.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.s_status == 'executed':
			return (service.identifier, "already running")
		else:
			managed.s_invoke()
			return (service.identifier, "invoked")

	@libweb.Resource.method()
	def environment(self, resource, parameters):
		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]
		return service.environment

	@libweb.Resource.method()
	def normalize(self, resource, parameters):
		"""
		# Normalize the set of services by shutting down any running
		# disabled services and starting any enabled services.

		# Command services are ignored by &normalize.
		"""

		for name, service in self.services.items():
			managed = self.managed[name]

			if service.actuates and service.s_status != 'executed':
				yield (service.identifier, managed.s_invoke())
			elif service.disabled and service.s_status == 'executed':
				yield (service.identifier, managed.subprocess.signal(signal.SIGTERM))

	@libweb.Resource.method()
	def report(self, resource, parameters):
		pass

	@libweb.Resource.method()
	def timestamp(self, resource, parameters):
		"""
		# Return rootd's perception of time.
		"""
		return sysclock.now().select("iso")

	# /if/usignal?number=9

	@libweb.Resource.method()
	def __resource__(self, resource, path, query, px):
		pass

	@libweb.Resource.method()
	def list(self, resource, parameters):
		"""
		# List the set of configured services.
		"""

		# list all if no filter
		service_set = [x for x in self.services.keys()]
		return service_set

	@libweb.Resource.method()
	def create(self, resource, parameters):
		"""
		# Create a service.
		"""

		name = parameters['service']

	@libweb.Resource.method()
	def void(self, resource, parameters):
		"""
		# Terminate the service and destroy it's stored configuration.
		"""

		name = parameters['service']
		m = self.managed[name]
		m.inhibit_recovery = True
		m.subprocess.signal(signal.SIGKILL)
		m.terminate()
		s = self.services[name]
		s.void()

	@libweb.Resource.method()
	def interface(self, resource, parameters):
		"""
		# Add a set of interfaces.
		"""

		name = parameters['service']
		service = self.services[name]
		return service.interfaces

class Service(kcore.Context):
	"""
	# Service daemon state and interface.

	# Manages the interactions to daemons and commands.

	# Service processors do not exit unless the service is *completely* removed
	# by an administrative instruction; disabling a service does not remove it.
	# They primarily respond to events in order to keep the daemon running.
	# Secondarily, it provides the administrative interface.

	# ! WARNING:
		# There is no exclusion primitive used to protect read or write operations,
		# so there are race conditions.

	# [ Properties ]
	# /s_minimum_runtime/
		# Identifies the minimum time required to identify a successful start.
	# /s_retry_wait/
		# Duration to wait before automatically attemping to start the daemon again.
	# /s_maximum_attempts/
		# Limit of attempts to make before giving up and inhibiting daemon start.
	"""

	# delay before faultd perceives the daemon as running
	s_minimum_runtime = timetypes.Measure.of(second=8)
	s_retry_wait = timetypes.Measure.of(second=2)
	s_maximum_attempts = 8

	def structure(self):
		p = [
			('s_status', self.s_status),
			('s_actuates', self.s_config.actuates),
			('s_identifier', self.s_config.identifier),
			('s_invocation', self.s_invocation),
		]

		return (p, [])

	s_critical = "critical.log"

	s_status = 'unknown'
	s_config = None
	s_invocation = None
	s_subprocess = None
	s_inhibit_recovery = None
	s_exit_events = ()

	def __init__(self, service):
		self.s_config = service
		self.s_exit_events = []
		self.s_status = 'terminated'
		self.s_process = None

	def actuate(self):
		self.controller.scheduling()
		self.s_update()
		self.s_last_known_time = sysclock.now()

		if self.s_config.actuates:
			self.critical(self.s_invoke)

	def s_invoke(self):
		"""
		# Invoke the service. Does nothing if &status is `'executed'`.
		"""

		if self.s_status == 'executed':
			return 'already running'

		cwd = os.getcwd()
		try:
			self.s_status = 'executed'
			service = self.s_config

			os.chdir(service.route.fullpath)
			fd = os.open(self.s_critical, os.O_APPEND|os.O_WRONLY|os.O_CREAT)

			subproc = kdispatch.Subprocess.from_invocation(self.s_invocation, stderr=fd, stdout=1)
			self.xact_dispatch(kcore.Transaction.create(subproc))
			self.s_last_known_time = sysclock.now()
			os.close(fd)
			self.s_process = subproc
		except BaseException as exc:
			self.s_status = 'exception'
			raise
		finally:
			os.chdir(cwd)

		return 'invoked'

	def s_was_running(self):
		lkt = self.s_last_known_time
		try:
			duration = lkt.measure(self.s_exit_events[-1][0])
		except:
			return False

		if duration >= self.s_minimum_runtime:
			return True
		else:
			return False

	def s_again(self):
		"""
		# Called when a non-command service exits.
		"""

		if self.s_was_running():
			del self.s_exit_events[:]
			self.s_invoke()
		elif len(self.s_exit_events) >= self.s_maximum_attempts:
			# Force administrative intervention.
			self.s_inhibit_recovery = True
			self.s_status = 'exits'
		else:
			self.s_status = 'waiting'
			self.controller.scheduler.defer(self.s_retry_wait, self.s_invoke)

	def s_update(self):
		"""
		# Create or Update the KInvocation instance used to launch the daemon.
		"""

		# KInvocation used to run the command.
		service = self.s_config
		command_def = service.execution()
		if command_def[0] is None:
			command_def = ()
			return

		env = dict(os.environ.items())

		if service.environment:
			env.update(service.environment)

		env['SERVICE_NAME'] = service.identifier

		ki = libexec.KInvocation(*command_def, environ=env, set_process_group=True)
		self.s_invocation = ki

	def xact_void(self, xact):
		if self.terminating:
			self.finish_termination()
			return

		subproc = xact.xact_context
		pid_exit = subproc.sp_only

		if self.s_status != 'exception':
			self.s_status = 'terminated'

		self.s_exit_events.append((sysclock.now(), pid_exit))
		self.s_last_exit_status = pid_exit

		if self.s_inhibit_recovery != True:
			if self.s_config.actuates:
				self.s_again()
			elif self.s_inhibit_recovery == False:
				# restarted
				self.s_inhibit_recovery = None
				self.s_again()

	def s_close(self):
		self.s_process.sp_signal(signal.SIGTERM)

	def terminate(self):
		if not self.functioning:
			return

		self.start_termination()
		if self.s_process is not None and not self.s_process.terminated:
			self.s_close()
		else:
			self.finish_termination()

class Set(kcore.Context):
	"""
	# Set of &Service transactions managing the presence of the service process.
	"""

	def __init__(self, route):
		self.r_path = route
		self.r_services = {} # name to xact

	def structure(self):
		p = [
			('r_path', self.r_path),
		]
		return (p, [])

	def xact_void(self, final):
		if self.terminating:
			self.finish_termination()

	def xact_exit(self, xact):
		# log unexpected exits
		pass

	def actuate(self):
		"""
		# Create the faultd context if it does not exist.
		# This is performed in actuate because it is desirable
		# to trigger a &system.process.Panic when an exception occurs.
		"""

		self.system.process.system_event_connect(('signal', 'terminate'), self, self.r_terminate)

		srv = service.Configuration(self.r_path, 'rootd')
		if service.environment not in os.environ:
			os.environ[service.environment] = self.r_path.fullpath

		# check process running
		srv.prepare()
		srv.load()

		srv.pid = os.getpid()
		srv.store_pid()
		self.root = srv
		srv.critical("[<> started root daemon]")
		os.chdir(srv.route.fullpath)

		# root's service instance will be loaded again in boot.
		# this reference will be simply dropped.

		rd = self.r_daemons = self.r_path / 'daemons'
		srv_list = rd.subnodes()[0]
		self.r_services.update(
			(x.identifier, service.Configuration(x, x.identifier))
			for x in srv_list
		)

		self.critical(self.r_boot)

	def terminate(self):
		self.start_termination()
		for x in self.controller.iterprocessors():
			if x is not self:
				x.terminate()

	def r_terminate(self):
		from ..system import kernel
		import signal
		kernel.exit_by_signal(signal.SIGTERM)
		self.controller.terminate()

	def r_install(self, srv:service.Configuration):
		"""
		# Install the service's manager for execution.
		"""

		d = Service(srv)
		x = self.r_services[srv.identifier] = kcore.Transaction.create(d)
		self.xact_dispatch(x)

	def r_boot(self):
		"""
		# Start all the *actuating* services and mention all the disabled ones.
		"""

		# Invocation; poll configuration and launch.
		for sn, s in self.r_services.items():
			s.load()
			self.r_install(s)
